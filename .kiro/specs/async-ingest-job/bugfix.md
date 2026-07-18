# Bugfix Requirements Document

## Introduction

Importing or rescanning a folder of documents in the ISOStandardsKB macOS app fails with repeated `NSURLErrorTimedOut (-1001)` errors against `http://127.0.0.1:8742/ingest`. The Swift `BackendClient` uses `URLSession.shared`, whose default `timeoutIntervalForRequest` is 60 seconds. The FastAPI `POST /ingest` endpoint runs `IngestionPipeline.ingest_library(path, name)` synchronously inside the request, which takes minutes for a folder of PDFs/DOCX with Ollama embedding generation. The request exceeds the 60s client timeout and fails before the backend finishes, so the user's import appears to fail even though work may still be running server-side.

The fix (user-chosen Option B) makes ingestion asynchronous: `POST /ingest` enqueues a background job and returns a job ID immediately, a new status endpoint reports progress and final results, and the Swift client submits the job then polls for status. Because individual requests become short, the 60s timeout is no longer exceeded.

## Bug Analysis

### Current Behavior (Defect)

When a folder is imported or rescanned, the synchronous ingestion request outlives the client's 60-second timeout.

1.1 WHEN a folder whose ingestion (parsing + Ollama embedding) takes longer than the client request timeout is submitted to `POST /ingest` THEN the system holds the HTTP connection open for the full synchronous duration of `ingest_library`, causing the Swift `URLSession.shared` request to fail with `NSURLErrorTimedOut (-1001)`.

1.2 WHEN the `POST /ingest` request times out on the client THEN `IndexCoordinator.importFolder` / `rescanFolder` surface an "Indexing failed" / "Rescan failed" message even though the backend may still be processing the folder.

1.3 WHEN ingestion is running THEN the system provides no incremental progress to the app; `IndexCoordinator.progress` and `lastMessage` cannot be updated because the single blocking request only returns after all work completes (or times out first).

### Expected Behavior (Correct)

2.1 WHEN a folder is submitted to `POST /ingest` THEN the system SHALL enqueue a background ingestion job and return a job identifier immediately in a short-lived response that completes well within the client request timeout.

2.2 WHEN the app queries the status endpoint (e.g. `GET /ingest/status/{job_id}`) for a known job id THEN the system SHALL return the job's current state (e.g. queued, running, completed, failed) and, on completion, the final result counts (`indexed`, `skipped`, `errors`) matching the shape previously returned by the synchronous endpoint.

2.3 WHEN `IndexCoordinator.importFolder` / `rescanFolder` runs THEN the system SHALL submit the job, poll the status endpoint until the job reaches a terminal state, and update the existing `isIndexing`, `progress`, and `lastMessage` fields from the polled status rather than failing on a timed-out single request.

2.4 WHEN a background ingestion job finishes successfully THEN the system SHALL report the same indexed/skipped/errors summary to the user that a completed synchronous ingest would have produced.

2.5 WHEN a background ingestion job fails or the requested path is invalid (e.g. not a directory) THEN the system SHALL surface the failure to the app via the job's status/response so the user sees an accurate error message.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a folder is small enough that ingestion completes quickly THEN the system SHALL CONTINUE TO index it and report the same `indexed`/`skipped`/`errors` counts as before.

3.2 WHEN `importFolder` is called with `watch: true` THEN the system SHALL CONTINUE TO start the folder watcher after successful ingestion and reflect the "watching for changes" state.

3.3 WHEN any `/ingest` or status request is made THEN the system SHALL CONTINUE TO require the existing Bearer token authentication via the protected router.

3.4 WHEN other endpoints (`/search`, `/ask`, `/libraries`, `/documents`, `/watch/start`, `/watch/stop`, `/health`, delete endpoints) are called THEN the system SHALL CONTINUE TO behave exactly as before, unaffected by the ingestion change.

3.5 WHEN the `no_embed` option is passed to ingestion THEN the system SHALL CONTINUE TO honor it, skipping embedding generation as before.

## Bug Condition Derivation

**Key Definitions:**
- **F**: The original backend + client behavior — `POST /ingest` runs `ingest_library` synchronously within one request; the app makes a single blocking call bounded by the 60s `URLSession.shared` timeout.
- **F'**: The fixed behavior — `POST /ingest` enqueues a background job and returns a job id; a status endpoint reports progress/result; the app polls until terminal state.

**Bug Condition Function** — identifies the inputs that trigger the bug:

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type IngestRequest (valid directory of documents to index)
  OUTPUT: boolean

  // The bug manifests whenever synchronous ingestion of the folder
  // takes longer than the client's request timeout.
  RETURN X.path is a valid directory
     AND syncIngestDuration(X) > clientRequestTimeout   // default 60s
END FUNCTION
```

**Property: Fix Checking** — desired behavior for buggy inputs:

```pascal
FOR ALL X WHERE isBugCondition(X) DO
  jobId  ← submitIngest'(X)          // returns quickly, within timeout
  ASSERT jobId is defined AND submitDuration(X) < clientRequestTimeout

  status ← pollUntilTerminal'(jobId) // short polling requests
  ASSERT status.state IN {completed, failed}
  ASSERT no request in the flow fails with NSURLErrorTimedOut
  IF status.state = completed THEN
    ASSERT status.result HAS {indexed, skipped, errors}
  END IF
END FOR
```

**Property: Preservation Checking** — non-buggy inputs behave identically:

```pascal
FOR ALL X WHERE NOT isBugCondition(X) DO
  // Small/fast folders, watch behavior, auth, no_embed, and all other
  // endpoints produce the same observable result as before.
  ASSERT observableResult(F'(X)) = observableResult(F(X))
END FOR
```
