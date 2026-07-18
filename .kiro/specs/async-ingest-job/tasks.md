# Implementation Plan

- [x] 1. Write bug condition exploration test (slow synchronous ingest + missing status endpoint)
  - **Property 1: Bug Condition** - Long ingestion blocks past the client timeout instead of returning a job id
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the synchronous `POST /ingest` holds the connection open past the request timeout and that no status channel exists
  - **Scoped PBT Approach**: This is a deterministic architectural bug; scope the property to concrete failing cases (a valid directory whose ingestion is simulated to exceed a small configured timeout), parameterized over a few simulated durations to model `syncIngestDuration(X) > clientRequestTimeout`
  - Add a pytest module (e.g. `tests/test_async_ingest.py`) that builds the FastAPI app via `create_app` with a `TestClient`, using a valid Bearer token
  - Monkeypatch `IngestionPipeline.ingest_library` to sleep longer than a small configured timeout (models the 60s `URLSession.shared` timeout) per Bug Condition `isBugCondition(X) = isValidDirectory(X.path) AND syncIngestDuration(X) > clientRequestTimeout`
  - Assert the UNFIXED `POST /ingest` does NOT return a `job_id` within the timeout window (it blocks for the full synchronous `ingest_library` duration) - test case 1 from design "Slow synchronous ingest blocks"
  - Assert the same blocking occurs when invoked via the rescan path - test case 2 from design "Rescan blocks the same way"
  - Assert `GET /ingest/status/<any>` returns `404` because the route does not exist on unfixed code - test case 3 from design "No status endpoint exists"
  - The test assertions should match the Expected Behavior in Property 1: submit returns a `job_id` fast (within timeout), status reaches a terminal state, no request times out, and `completed` carries `{indexed, skipped, errors}`
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists: no fast submit, no status endpoint)
  - Document counterexamples found (e.g. "POST /ingest with a slow folder does not return within the timeout window; GET /ingest/status/{id} 404s because the route is absent")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-buggy inputs and other endpoints behave identically
  - **IMPORTANT**: Follow observation-first methodology - run the UNFIXED code first, record actual outputs, then encode those observations as tests that must still pass after the fix
  - Observe on UNFIXED code: a small/fast fixture folder submitted to `POST /ingest` returns `{indexed, skipped, errors}` counts; record the exact counts for the fixture (Requirement 3.1)
  - Observe on UNFIXED code: `importFolder`/`watch: true` starts the folder watcher after successful ingest and reflects "watching for changes" (Requirement 3.2)
  - Observe on UNFIXED code: `POST /ingest` and any status request without a valid Bearer token are rejected exactly like other protected routes (Requirement 3.3)
  - Observe on UNFIXED code: submitting a non-directory path returns the surfaced `400 "Not a directory"` error (Requirement 2.5)
  - Observe on UNFIXED code: `no_embed: true` skips embedding generation (Requirement 3.5)
  - Observe on UNFIXED code: `/search`, `/ask`, `/libraries`, `/documents`, `/watch/start`, `/watch/stop`, `/health`, and delete endpoints respond as before (Requirement 3.4)
  - Write property-based tests capturing these observed behavior patterns (property-based testing generates many inputs for stronger preservation guarantees):
    - For randomized fast fixtures, async result counts equal the synchronous pipeline's counts for the same input (Requirement 3.1)
    - For randomized non-ingest requests across the other endpoints, responses match the pre-fix contract (Requirement 3.4)
    - Auth enforcement holds for `POST /ingest` and the status route across randomized missing/invalid tokens (Requirement 3.3)
  - Include the unknown-job-id preservation case as a documented expectation for after the fix: `GET /ingest/status/<random>` returns `404`
  - Run tests on UNFIXED code (skip/xfail only the assertions that depend on routes introduced by the fix, e.g. the status endpoint and job-id counts; the endpoint-contract, auth, not-a-directory, and `no_embed` observations must PASS now)
  - **EXPECTED OUTCOME**: Preservation observations of existing behavior PASS (this confirms the baseline to preserve)
  - Mark task complete when tests are written, run, and the existing-behavior observations pass on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 2.5_

- [x] 3. Fix: make ingestion asynchronous (submit + status endpoints and Swift submit-then-poll)

  - [x] 3.1 Add in-memory job registry and job runner in `indexer/api.py`
    - Inside `create_app`, add a closure-scoped `jobs: dict[str, dict]` (alongside `watchers`); each entry holds `{"state": str, "result": dict | None, "error": str | None, "created_at": float}`
    - Add a `threading.Lock` guarding all mutations of `jobs` so the background worker and request threads do not race
    - State transitions: `queued` -> `running` -> `completed` | `failed`
    - Implement `_run_ingest_job(job_id, path, name, no_embed)`: set state `running`; open its own `Database(db_path)` (fresh per-job connection, NOT the request-scoped `get_db()` connection); build `IngestionPipeline(db, figures_dir, embed=not no_embed)` (preserving `no_embed`); call `ingest_library(path, name)`, store the returned dict in `result`, set state `completed`; on exception record `str(exc)` in `error` and set state `failed`; always close the job DB connection in a `finally`
    - Add a module-level single-worker `ThreadPoolExecutor` to run jobs off the event loop (also naturally serializes ingest jobs, matching prior one-at-a-time behavior)
    - _Bug_Condition: isBugCondition(input) = isValidDirectory(input.path) AND syncIngestDuration(input) > clientRequestTimeout_
    - _Expected_Behavior: submit returns a job id quickly; job runs on a background worker and reaches a terminal state carrying result/error (Property 1)_
    - _Preservation: fresh per-job DB connection and `embed=not no_embed` preserve pipeline behavior and `no_embed` handling_
    - _Requirements: 2.1, 2.4, 2.5, 3.5_

  - [x] 3.2 Rework `POST /ingest` into a fast submit endpoint
    - Keep the existing `path.is_dir()` check so an invalid directory is rejected at submit time with the existing `HTTPException(400, "Not a directory: ...")` (fast, surfaced directly to the client)
    - On success: generate `job_id = uuid4().hex`, register a `queued` entry, schedule `_run_ingest_job` on the executor, and return `{"job_id": job_id, "status": "queued"}` immediately
    - Prune terminal jobs older than a threshold (e.g. 1 hour) on new submissions to bound memory, without dropping in-flight jobs
    - _Bug_Condition: isBugCondition(input) from design_
    - _Expected_Behavior: submitDuration(X) < clientRequestTimeout AND jobId is defined (Property 1)_
    - _Preservation: not-a-directory 400 still raised at submit time (Requirement 2.5)_
    - _Requirements: 2.1, 2.5_

  - [x] 3.3 Add `GET /ingest/status/{job_id}` on the protected router
    - Look up `job_id`; if absent raise `HTTPException(404, "Unknown job: ...")`
    - Otherwise return `{"job_id", "status": state}` plus `"result"` when `completed` and `"error"` when `failed`
    - Register on the `protected` router so Bearer auth is enforced identically to other protected routes
    - _Bug_Condition: isBugCondition(input) from design_
    - _Expected_Behavior: polling reaches terminal state; completed carries {indexed, skipped, errors}; failed carries error (Property 1)_
    - _Preservation: Bearer auth enforced via protected router (Requirement 3.3); unknown id -> 404_
    - _Requirements: 2.2, 2.4, 2.5, 3.3_

  - [x] 3.4 Update `BackendClient.swift` to submit and poll
    - Change `ingest(path:name:noEmbed:)` to decode the submit response and return the `job_id` string; add `struct IngestJob: Decodable { let jobId: String; let status: String }` with `job_id`/`status` coding keys
    - Add `func ingestStatus(jobId: String) async throws -> IngestStatus` hitting `GET /ingest/status/{jobId}`, where `struct IngestStatus: Decodable` decodes `{status, result?: {indexed, skipped, errors}, error?}`
    - Reuse the existing `get`/`applyAuth`/`validate` helpers so Bearer auth is preserved; keep `URLSession.shared` (submit and each poll are short requests, so the default 60s timeout is acceptable)
    - _Bug_Condition: single blocking call bounded by 60s URLSession.shared timeout_
    - _Expected_Behavior: ingest() returns a job id fast; ingestStatus() reads terminal state (Property 1)_
    - _Preservation: URLSession.shared and Bearer auth unchanged (Requirement 3.3)_
    - _Requirements: 2.1, 2.2, 3.3_

  - [x] 3.5 Update `IndexCoordinator.swift` importFolder/rescanFolder to submit-then-poll
    - `importFolder`: submit via `backend.ingest(...)` to get a `jobId`, then loop calling `backend.ingestStatus(jobId:)` with a short sleep (1-2s), updating `lastMessage`/`progress` while `running`; on `completed` set `"Indexed N files (E errors)"` from `result.indexed`/`errors`; if `watch`, call `startWatching` and append `" - watching for changes"`; on `failed` set `"Indexing failed: <error>"`; preserve existing message formats
    - `rescanFolder`: same submit-then-poll pattern; on `completed` set `"Rescan: <indexed> new, <skipped> skipped"` and return a stats dict shaped like before (`indexed`/`skipped`/`errors`); on `failed` set `"Rescan failed: <error>"` and return `.failure`
    - Keep `isIndexing` true for the full submit+poll duration via the existing `defer { isIndexing = false }`; update `progress` in a bounded/indeterminate way
    - _Bug_Condition: importFolder/rescanFolder previously made a single blocking call that timed out (Requirements 1.2, 1.3)_
    - _Expected_Behavior: submit-then-poll updates isIndexing/progress/lastMessage until terminal state (Property 1)_
    - _Preservation: watch-after-import behavior and message formats unchanged (Requirement 3.2)_
    - _Requirements: 2.3, 2.4, 2.5, 3.2_

  - [x] 3.6 Verify bug condition exploration test now passes (fix checking)
    - **Property 1: Expected Behavior** - Long ingestion completes via async job instead of timing out
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior; when it passes it confirms the expected behavior is satisfied
    - With the slow-pipeline patch in place, assert `POST /ingest` returns a `job_id` near-instantly (submit within the timeout window), early status is `queued`/`running`, and after the simulated work finishes the status becomes `completed` with a `result` carrying `indexed`/`skipped`/`errors`
    - Add/enable the failure-path assertion: when the patched pipeline raises, the job reaches terminal `failed` with an `error` message
    - Assert no request in the flow blocks past the timeout window
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms the bug is fixed for all buggy inputs)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.7 Verify preservation tests still pass (preservation checking)
    - **Property 2: Preservation** - Non-buggy inputs and other endpoints behave identically
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Confirm small-folder async counts equal the synchronous pipeline's counts for the same fixture (Requirement 3.1)
    - Confirm watch-after-import still starts the watcher and reflects "watching for changes" (Requirement 3.2)
    - Confirm Bearer auth is still enforced on `POST /ingest` and `GET /ingest/status/{id}` (Requirement 3.3)
    - Confirm the not-a-directory `400` is still surfaced (Requirement 2.5) and `no_embed` is still honored (Requirement 3.5)
    - Confirm `/search`, `/ask`, `/libraries`, `/documents`, `/watch/start`, `/watch/stop`, `/health`, and delete endpoints are unchanged (Requirement 3.4), and `GET /ingest/status/<random>` returns `404`
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 2.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run the full backend pytest suite (existing tests plus the new async ingest tests) and confirm all pass
  - Build/compile the Swift target to confirm `BackendClient` and `IndexCoordinator` changes compile
  - Ensure all tests pass; ask the user if questions arise
