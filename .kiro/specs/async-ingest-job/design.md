# Async Ingest Job Bugfix Design

## Overview

Importing or rescanning a folder fails because `POST /ingest` runs the entire
`IngestionPipeline.ingest_library` synchronously inside the HTTP request. For a
real folder of PDFs/DOCX with Ollama embedding generation this takes minutes,
which exceeds the Swift client's 60s `URLSession.shared` request timeout. The
request fails with `NSURLErrorTimedOut (-1001)` and the app reports "Indexing
failed" / "Rescan failed" even though the backend may still be working.

The fix makes ingestion asynchronous while keeping the request/response
contract observable and unchanged for callers that only care about final
counts:

- `POST /ingest` becomes a fast **submit** endpoint. It validates the path,
  registers a job in an in-memory registry keyed by a generated `job_id`, kicks
  off `ingest_library` on a background worker, and returns `{job_id, status}`
  immediately (well within the 60s timeout).
- A new `GET /ingest/status/{job_id}` reports the job's lifecycle state
  (`queued` / `running` / `completed` / `failed`), the final
  `{indexed, skipped, errors}` on completion, and an `error` message on failure.
  Unknown ids return `404`.
- The Swift `BackendClient.ingest()` returns a job id, a new
  `pollIngestStatus(jobId:)` hits the status endpoint, and
  `IndexCoordinator.importFolder` / `rescanFolder` submit-then-poll until a
  terminal state, updating `isIndexing` / `progress` / `lastMessage` from the
  polled status.

Because every individual request is now short (submit is near-instant, each poll
is a small read), no request in the flow approaches the 60s timeout. The app is
local single-user, so an in-memory job registry is acceptable.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — a valid directory
  whose synchronous ingestion duration exceeds the client request timeout
  (default 60s), so the single blocking `POST /ingest` call fails with
  `NSURLErrorTimedOut`.
- **Property (P)**: The desired behavior for buggy inputs — submitting returns a
  job id quickly, polling reaches a terminal state (`completed`/`failed`), no
  request times out, and on completion the same `{indexed, skipped, errors}`
  summary is available.
- **Preservation**: Existing observable behavior that must stay unchanged —
  final result counts for small/fast folders, watch-after-import, Bearer auth,
  `no_embed` handling, the "not a directory" error, and all other endpoints.
- **F**: Original behavior — `POST /ingest` runs `ingest_library` synchronously;
  the app makes a single blocking call bounded by the 60s timeout.
- **F'**: Fixed behavior — `POST /ingest` enqueues a background job and returns a
  job id; `GET /ingest/status/{job_id}` reports progress/result; the app polls
  until terminal state.
- **ingest_library**: The method in `indexer/pipeline.py` that walks a directory,
  ingests each supported file, and returns `{indexed, skipped, errors, files}`.
- **job registry**: An in-memory dict in `indexer/api.py` keyed by `job_id` that
  holds each job's state, result, and error message.
- **IndexCoordinator**: The `@MainActor` class in
  `ISOStandardsKB/Services/IndexCoordinator.swift` that drives import/rescan and
  publishes `isIndexing`, `progress`, and `lastMessage` to the UI.

## Bug Details

### Bug Condition

The bug manifests whenever a **valid directory** is submitted to `POST /ingest`
and the synchronous ingestion of that folder takes longer than the client's
request timeout. The endpoint holds the HTTP connection open for the full
duration of `ingest_library`, so the client's `URLSession.shared` request
(default `timeoutIntervalForRequest` = 60s) fails with `NSURLErrorTimedOut
(-1001)` before the backend returns. The root cause is architectural: work whose
duration is unbounded by folder size is performed inside a single
request/response cycle bounded by a fixed client timeout.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type IngestRequest { path, name, no_embed }
  OUTPUT: boolean

  RETURN isValidDirectory(input.path)
         AND syncIngestDuration(input) > clientRequestTimeout   // default 60s
END FUNCTION
```

### Examples

- **Large PDF library with embeddings** — Import a folder of ~30 ISO PDFs with
  Ollama embedding enabled. Expected: import succeeds and reports indexed/errors
  counts. Actual (F): after ~60s the app shows "Indexing failed: … timed out
  (-1001)" while the backend keeps processing.
- **Rescan of a populated library** — Rescan a previously indexed folder that
  now has several new large documents. Expected: "Rescan: N new, M skipped".
  Actual (F): "Rescan failed: … timed out (-1001)".
- **Mixed DOCX/PDF folder, slow embeddings** — Ollama running but slow.
  Expected: eventual success summary. Actual (F): timeout at 60s.
- **Edge case — small folder (2 short files)** — Completes in a few seconds.
  Expected and Actual (F): succeeds with correct counts. This is NOT a bug
  condition and must be preserved.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Small/fast folders continue to index and report the same
  `{indexed, skipped, errors}` counts as before (Requirement 3.1).
- `importFolder` with `watch: true` continues to start the folder watcher after
  successful ingestion and reflect the "watching for changes" state
  (Requirement 3.2).
- Every `/ingest` and status request continues to require the existing Bearer
  token via the protected router (Requirement 3.3).
- All other endpoints (`/search`, `/ask`, `/libraries`, `/documents`,
  `/watch/start`, `/watch/stop`, `/health`, delete endpoints) behave exactly as
  before (Requirement 3.4).
- The `no_embed` option is still honored, skipping embedding generation
  (Requirement 3.5).
- The "Not a directory" validation error is still surfaced to the client so the
  user sees an accurate message (Requirement 2.5).

**Scope:**
All inputs that do NOT satisfy the bug condition should be observably unaffected
by this fix. This includes:
- Small/fast folders whose sync ingestion would have finished within the timeout.
- Invalid paths (non-directory) — must still produce a surfaced error.
- Requests to every endpoint other than `POST /ingest` and the new status
  endpoint.
- Auth behavior and `no_embed` handling.

**Note:** The expected correct behavior for buggy inputs is defined in the
Correctness Properties section (Property 1). This section focuses on what must
NOT change.

## Hypothesized Root Cause

Based on the bug analysis, the cause is well understood (this is a chosen
redesign rather than an unknown defect), but stated for completeness:

1. **Synchronous long-running work inside a request handler**: `POST /ingest`
   calls `pipeline.ingest_library(path, name)` directly and only returns after
   all parsing, figure extraction, and embedding complete. Duration scales with
   folder size and Ollama latency, which is unbounded relative to the client
   timeout.

2. **Fixed client-side request timeout**: The Swift client uses
   `URLSession.shared`, whose default `timeoutIntervalForRequest` is 60s. Any
   single request exceeding this fails with `NSURLErrorTimedOut (-1001)`.

3. **No progress channel**: Because the single blocking call only returns at the
   end, `IndexCoordinator.progress` / `lastMessage` cannot update mid-run, so
   even a "still working" state cannot be shown.

The fix removes the mismatch by decoupling job duration from request duration:
submission and status polling are both short requests, so the fixed timeout is
never the binding constraint.

## Correctness Properties

Property 1: Bug Condition - Long ingestion completes via async job instead of timing out

_For any_ input where the bug condition holds (a valid directory whose
synchronous ingestion would exceed the client request timeout), the fixed
system SHALL return a job id from `POST /ingest` in a response that completes
within the client request timeout, and polling `GET /ingest/status/{job_id}`
SHALL eventually return a terminal state (`completed` or `failed`) with no
request in the flow failing with `NSURLErrorTimedOut`; when the state is
`completed` the status SHALL include a result with `indexed`, `skipped`, and
`errors` fields matching what a completed synchronous ingest would have
produced.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - Non-buggy inputs and other endpoints behave identically

_For any_ input where the bug condition does NOT hold (small/fast folders,
invalid paths, watch behavior, auth, `no_embed`, and all endpoints other than
async ingestion), the fixed system SHALL produce the same observable result as
the original system: the same `{indexed, skipped, errors}` counts for fast
folders, the same watcher-start behavior, the same Bearer-auth enforcement, the
same `no_embed` handling, the same "not a directory" error, and unchanged
behavior for all other endpoints.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct:

**File**: `indexer/api.py`

**Endpoint/Function**: `POST /ingest` (`ingest`) plus a new
`GET /ingest/status/{job_id}` on the protected router.

**Specific Changes**:

1. **In-memory job registry**: Add a module/closure-scoped
   `jobs: dict[str, dict]` inside `create_app` (alongside `watchers`). Each entry
   holds `{"state": str, "result": dict | None, "error": str | None,
   "created_at": float}`. State transitions: `queued` -> `running` ->
   `completed` | `failed`. A `threading.Lock` guards mutations so the background
   worker and request threads don't race.

2. **Job runner**: A helper `_run_ingest_job(job_id, path, name, no_embed)` that:
   - sets state to `running`,
   - opens its own `Database(db_path)` (a fresh connection per job — the request
     scoped `get_db()` connection must not be shared across threads),
   - builds `IngestionPipeline(db, figures_dir, embed=not no_embed)` (preserving
     `no_embed`),
   - calls `ingest_library(path, name)`, stores the returned dict in
     `result` and sets state `completed`,
   - on exception, records `str(exc)` in `error` and sets state `failed`,
   - always closes the job's DB connection in a `finally`.

3. **Rework `POST /ingest` into a submit endpoint**: Keep the existing
   `path.is_dir()` check so an invalid directory is rejected at **submit time**
   with the existing `HTTPException(400, "Not a directory: …")` (fast, surfaced
   directly to the client — Requirement 2.5). On success: generate
   `job_id = uuid4().hex`, register a `queued` entry, schedule
   `_run_ingest_job` on a background worker, and return
   `{"job_id": job_id, "status": "queued"}`.

4. **Background execution mechanism**: Use a small module-level
   `ThreadPoolExecutor` (or `threading.Thread`) rather than FastAPI
   `BackgroundTasks`, because ingestion is CPU/IO heavy and blocking; a thread
   keeps it off the event loop and lets the submit response return immediately.
   Note: FastAPI `BackgroundTasks` runs after the response is sent but would tie
   the job to request teardown semantics; an explicit executor + registry gives
   cleaner status tracking. A single-worker executor also naturally serializes
   ingest jobs, matching the previous one-at-a-time behavior.

5. **New status endpoint**: `GET /ingest/status/{job_id}` on the `protected`
   router. Look up `job_id`; if absent raise `HTTPException(404, "Unknown job:
   …")`. Otherwise return `{"job_id", "status": state}` plus `"result"` when
   `completed` and `"error"` when `failed`.

6. **Job lifecycle / cleanup**: Since this is a local single-user app, keep it
   simple: retain completed/failed entries so the client can read the final
   result, and prune on new submissions — e.g. when submitting, drop terminal
   jobs older than a threshold (say 1 hour) to bound memory. No persistence
   across server restarts is required; a lost job id simply yields a 404 and the
   client can resubmit.

**File**: `ISOStandardsKB/Services/BackendClient.swift`

7. **`ingest` returns a job id**: Change `ingest(path:name:noEmbed:)` to decode
   the submit response and return the `job_id` string (e.g.
   `struct IngestJob: Decodable { let jobId: String; let status: String }` with
   `job_id`/`status` coding keys), instead of returning `[String: Any]`.

8. **New `pollIngestStatus`**: Add
   `func ingestStatus(jobId: String) async throws -> IngestStatus` hitting
   `GET /ingest/status/{jobId}`, where `IngestStatus` decodes
   `{status, result?: {indexed, skipped, errors}, error?}`. Reuse the existing
   `get`/`applyAuth`/`validate` helpers so Bearer auth is preserved
   (Requirement 3.3).

9. **URLSession note**: Keep `URLSession.shared`. Because both submit and each
   poll are short requests, the default 60s `timeoutIntervalForRequest` is
   acceptable and no dedicated session/config is required. (A dedicated session
   is documented as optional but unnecessary.)

**File**: `ISOStandardsKB/Services/IndexCoordinator.swift`

10. **`importFolder` submit-then-poll**: Submit via `backend.ingest(...)` to get
    a `jobId`, then loop calling `backend.ingestStatus(jobId:)` with a short
    sleep between polls (e.g. 1–2s), updating `lastMessage`/`progress` while
    `running`. On `completed`, read `result.indexed`/`errors` and set
    `"Indexed N files (E errors)"`; if `watch`, call `startWatching` and append
    `" — watching for changes"` (Requirement 3.2). On `failed`, set
    `"Indexing failed: <error>"`. Preserve the existing message formats.

11. **`rescanFolder` submit-then-poll**: Same pattern; on `completed` set
    `"Rescan: <indexed> new, <skipped> skipped"` and return a stats dict shaped
    like before (`indexed`/`skipped`/`errors`) so callers are unaffected. On
    `failed`, set `"Rescan failed: <error>"` and return `.failure`.

12. **Progress updates**: With only coarse job state available, update
    `progress` in a bounded way (e.g. indeterminate/step-based) and keep
    `isIndexing` true for the full submit+poll duration via the existing
    `defer { isIndexing = false }`.

## Testing Strategy

### Validation Approach

Two-phase approach: first surface counterexamples that demonstrate the bug on
the unfixed code, then verify the fix resolves the bug condition and preserves
all non-buggy behavior. Backend behavior is testable with pytest against the
FastAPI app (`TestClient`); the timeout symptom itself is a client/duration
property best asserted via response-time and terminal-state checks plus a
simulated slow pipeline.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing
the fix, and confirm the root cause (synchronous work exceeding the request
timeout). If refuted, re-hypothesize.

**Test Plan**: Simulate a slow ingestion by monkeypatching
`IngestionPipeline.ingest_library` to sleep longer than a small configured
timeout, then observe that a synchronous `POST /ingest` does not return within
that window (modeling the 60s client timeout). Run against the UNFIXED endpoint
to demonstrate the blocking behavior.

**Test Cases**:
1. **Slow synchronous ingest blocks** — patch `ingest_library` to sleep beyond
   the test timeout; assert the unfixed `POST /ingest` call does not complete
   within the timeout window (will fail/block on unfixed code).
2. **Rescan blocks the same way** — same slow patch invoked via the rescan path
   (will fail on unfixed code).
3. **No status endpoint exists** — `GET /ingest/status/<any>` returns 404 for a
   missing route on unfixed code (documents the gap the fix fills).
4. **Edge — small folder returns quickly** — a fast fixture folder returns
   within the window on unfixed code (confirms the bug is duration-dependent, not
   universal).

**Expected Counterexamples**:
- The synchronous request holds open past the timeout window for slow folders.
- Possible causes confirmed: work runs inside the request handler; no async job;
  no status channel.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed
system returns a job id quickly and reaches a terminal state with the expected
result shape.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  submitStart := now()
  { job_id, status } := POST /ingest(input)
  ASSERT job_id is defined
  ASSERT now() - submitStart < clientRequestTimeout
  ASSERT status IN {"queued", "running"}

  final := pollUntilTerminal(GET /ingest/status/{job_id})
  ASSERT final.status IN {"completed", "failed"}
  ASSERT every request in the flow completed well under clientRequestTimeout
  IF final.status = "completed" THEN
    ASSERT final.result HAS {indexed, skipped, errors}
  END IF
END FOR
```

**Test Plan**: With the slow-pipeline patch still in place, assert `POST /ingest`
returns a `job_id` near-instantly, that early status is `queued`/`running`, and
that after the simulated work finishes the status becomes `completed` with a
`result` carrying `indexed`/`skipped`/`errors`. Add a variant where the patched
pipeline raises, asserting terminal `failed` with an `error` message.

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the
fixed system produces the same observable result as the original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT observableResult(F'(input)) = observableResult(F(input))
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation
because it generates many inputs across the domain and catches edge cases manual
tests miss. Capture the observable contract (final counts, auth, `no_embed`,
other endpoints) and assert the fixed system matches it.

**Test Plan**: Observe behavior on the current code for fast folders, auth,
`no_embed`, watch, and other endpoints, then encode those observations as tests
that must still pass after the fix.

**Test Cases**:
1. **Small-folder counts preserved** — submit a small fixture folder, poll to
   `completed`, assert `indexed`/`skipped`/`errors` equal the counts the
   synchronous pipeline produces for the same fixture (Requirement 3.1).
2. **Watch-after-import preserved** — with `watch: true`, assert the watcher is
   started after a completed job and the "watching for changes" state is
   reflected (Requirement 3.2).
3. **Auth preserved** — `POST /ingest` and `GET /ingest/status/{id}` without a
   valid Bearer token are rejected exactly like other protected routes
   (Requirement 3.3).
4. **Not-a-directory error preserved** — submitting a non-directory path returns
   the surfaced `400 "Not a directory"` error (Requirement 2.5).
5. **`no_embed` honored** — submit with `no_embed: true`; assert no embeddings
   are generated, matching prior behavior (Requirement 3.5).
6. **Other endpoints unchanged** — `/search`, `/ask`, `/libraries`,
   `/documents`, `/watch/start`, `/watch/stop`, `/health`, and delete endpoints
   respond as before (Requirement 3.4).
7. **Unknown job id** — `GET /ingest/status/<random>` returns `404`.

### Unit Tests

- Job registry state transitions: `queued` -> `running` -> `completed`/`failed`.
- `POST /ingest` returns `{job_id, status}` quickly; invalid directory still
  raises `400` at submit time.
- `GET /ingest/status/{job_id}`: known completed, known failed (with `error`),
  and unknown (`404`).
- `no_embed` propagated to the pipeline constructor.
- Swift decoding of the submit response (`IngestJob`) and status response
  (`IngestStatus`) including `result` and `error` variants.

### Property-Based Tests

- For randomized job outcomes (success with varied counts, failures with varied
  messages), the status endpoint always reports a consistent terminal state and
  the correct result/error shape.
- For randomized non-ingest requests across the other endpoints, responses match
  the pre-fix contract (preservation).
- For randomized fast fixtures, async result counts equal the synchronous
  pipeline's counts for the same input.

### Integration Tests

- Full submit-then-poll flow through the FastAPI app: submit a fixture folder,
  poll until `completed`, verify final counts and that documents/libraries were
  created.
- Watch flow: import with `watch: true`, then confirm the watcher is registered
  and a subsequent stop succeeds.
- Failure flow: submit a path that causes the pipeline to raise; poll to
  `failed`; verify the client surfaces the error message.
- Concurrency/lifecycle: submit two jobs; verify each has an independent
  `job_id` and status, and that terminal-job pruning does not drop an
  in-flight job.
