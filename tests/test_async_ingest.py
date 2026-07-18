"""Bug condition exploration test for the async-ingest-job bugfix spec.

Property 1: Bug Condition - Long ingestion blocks past the client timeout
instead of returning a job id.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5**

CRITICAL SEMANTICS: This module is EXPECTED TO FAIL on the *unfixed* code. The
failure is the success case for a bug-condition exploration test: it proves the
bug exists. The assertions below encode the EXPECTED (fixed) behavior described
in Property 1, so once the async submit + status endpoints are implemented the
same test will pass.

The bug: ``POST /ingest`` runs ``IngestionPipeline.ingest_library`` synchronously
inside the request handler. For a real folder this takes minutes, exceeding the
Swift ``URLSession.shared`` 60s ``timeoutIntervalForRequest`` and failing with
``NSURLErrorTimedOut (-1001)``. There is no status channel to poll.

We model the bug deterministically:
  - A real temporary valid directory satisfies ``isValidDirectory(X.path)``.
  - ``ingest_library`` is monkeypatched to sleep for a simulated ``slow_duration``
    that stands in for ``syncIngestDuration(X)``.
  - A small ``CLIENT_TIMEOUT`` stands in for ``clientRequestTimeout`` (the 60s
    URLSession timeout, scaled down so the test is fast).
  - The bug condition ``syncIngestDuration(X) > clientRequestTimeout`` holds for
    every parameterized ``slow_duration`` (all > CLIENT_TIMEOUT).
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from indexer import auth
from indexer.api import _ingest_executor, create_app
from indexer.pipeline import IngestionPipeline

# Scaled-down stand-in for the 60s URLSession.shared request timeout. Any single
# request that does not complete within this window models a client-side
# NSURLErrorTimedOut (-1001).
CLIENT_TIMEOUT = 0.5

# Simulated synchronous ingest durations (seconds). Each is > CLIENT_TIMEOUT, so
# every case satisfies isBugCondition(X) = isValidDirectory AND
# syncIngestDuration(X) > clientRequestTimeout.
SLOW_DURATIONS = [1.0, 1.5, 2.0]

TOKEN = "test-token-async-ingest"


@pytest.fixture(autouse=True)
def _drain_ingest_executor() -> None:
    """Keep the shared single-worker ingest executor isolated between tests.

    ``POST /ingest`` submits jobs fire-and-forget onto a module-level
    single-worker ``ThreadPoolExecutor``. The blocking-exploration tests submit
    slow-sleeping jobs and return as soon as the fast submit responds, so those
    jobs are still running/queued when the next test starts. Because the worker
    is shared and serial, that backlog would starve a later test's job. After
    each test we enqueue a sentinel and wait for it: since the queue is FIFO on
    one worker, the sentinel only completes once every previously submitted job
    has finished, guaranteeing an idle worker for the next test.
    """
    yield
    _ingest_executor.submit(lambda: None).result(timeout=60)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Build the FastAPI app via create_app with a valid Bearer token set."""
    # Prime the module-level token so verify_token accepts our Bearer header.
    auth._current_token = TOKEN
    db_path = tmp_path / "test.db"
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(db_path=db_path, figures_dir=figures_dir)
    return TestClient(app)


@pytest.fixture
def valid_dir() -> Path:
    """A real temporary directory so isValidDirectory(X.path) holds."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _patch_slow_ingest(monkeypatch: pytest.MonkeyPatch, slow_duration: float) -> None:
    """Make ingest_library sleep longer than CLIENT_TIMEOUT (models slow folder)."""

    def slow_ingest_library(self, library_path, library_name=None):
        time.sleep(slow_duration)
        return {"indexed": 3, "skipped": 1, "errors": 0, "files": []}

    monkeypatch.setattr(
        IngestionPipeline, "ingest_library", slow_ingest_library
    )


# ---------------------------------------------------------------------------
# Test case 1 (design): "Slow synchronous ingest blocks"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("slow_duration", SLOW_DURATIONS)
def test_slow_synchronous_ingest_blocks(
    client: TestClient,
    valid_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    slow_duration: float,
) -> None:
    """POST /ingest should return a job_id fast (within CLIENT_TIMEOUT).

    Expected (fixed) behavior per Property 1: submit returns quickly with a
    job_id and status in {queued, running}, well within the client timeout.

    On UNFIXED code the handler blocks for the full slow_duration and returns
    the raw {indexed, skipped, errors, files} dict with NO job_id, so the
    submit-within-timeout assertion FAILS. That failure is the counterexample.
    """
    _patch_slow_ingest(monkeypatch, slow_duration)

    start = time.monotonic()
    resp = client.post(
        "/ingest",
        json={"path": str(valid_dir), "name": "lib"},
        headers=_auth_headers(),
    )
    elapsed = time.monotonic() - start

    # Expected-behavior assertions (Property 1: fast submit returning a job_id).
    # These FAIL on unfixed code because the request blocks for the whole
    # synchronous ingest_library duration and returns no job_id.
    assert elapsed < CLIENT_TIMEOUT, (
        f"submit blocked for {elapsed:.2f}s (>= client timeout {CLIENT_TIMEOUT}s); "
        f"synchronous ingest held the connection open for the full "
        f"ingest_library duration ({slow_duration}s) instead of returning fast"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body, (
        f"POST /ingest returned no job_id (got keys {sorted(body)}); "
        f"the unfixed endpoint returns the synchronous ingest result instead of "
        f"enqueuing a background job"
    )
    assert body.get("status") in {"queued", "running"}


# ---------------------------------------------------------------------------
# Test case 2 (design): "Rescan blocks the same way"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("slow_duration", SLOW_DURATIONS)
def test_rescan_blocks_the_same_way(
    client: TestClient,
    valid_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    slow_duration: float,
) -> None:
    """The rescan path (re-submitting an already-known folder) blocks identically.

    Rescan is driven through the same POST /ingest submit endpoint (the app has
    no separate rescan route; IndexCoordinator.rescanFolder re-ingests via
    /ingest). Expected behavior: a fast job_id submit. On unfixed code it blocks
    for the full slow_duration exactly like the initial import.
    """
    _patch_slow_ingest(monkeypatch, slow_duration)

    start = time.monotonic()
    resp = client.post(
        "/ingest",
        json={"path": str(valid_dir), "name": "lib"},
        headers=_auth_headers(),
    )
    elapsed = time.monotonic() - start

    assert elapsed < CLIENT_TIMEOUT, (
        f"rescan submit blocked for {elapsed:.2f}s (>= client timeout "
        f"{CLIENT_TIMEOUT}s); the synchronous ingest held the connection open"
    )
    body = resp.json()
    assert "job_id" in body, (
        "rescan via POST /ingest returned no job_id; the unfixed endpoint runs "
        "ingest_library synchronously instead of enqueuing a job"
    )


# ---------------------------------------------------------------------------
# Test case 3 (design): "No status endpoint exists"
# ---------------------------------------------------------------------------
def test_status_endpoint_reaches_terminal_state(
    client: TestClient,
    valid_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After submitting, polling GET /ingest/status/{job_id} reaches a terminal
    state carrying {indexed, skipped, errors}.

    Expected (fixed) behavior per Property 1. On unfixed code the status route
    does not exist, so GET /ingest/status/{job_id} returns 404 and there is no
    job_id to poll for in the first place -> this assertion FAILS, documenting
    the missing status channel.
    """
    _patch_slow_ingest(monkeypatch, 1.0)

    resp = client.post(
        "/ingest",
        json={"path": str(valid_dir), "name": "lib"},
        headers=_auth_headers(),
    )
    body = resp.json()
    job_id = body.get("job_id")
    assert job_id is not None, (
        "no job_id returned from POST /ingest, so there is no status channel to "
        "poll (the unfixed code has no async job)"
    )

    # Poll until terminal state; no single request should approach the timeout.
    deadline = time.monotonic() + 5.0
    terminal = None
    while time.monotonic() < deadline:
        poll_start = time.monotonic()
        status_resp = client.get(
            f"/ingest/status/{job_id}", headers=_auth_headers()
        )
        poll_elapsed = time.monotonic() - poll_start
        assert poll_elapsed < CLIENT_TIMEOUT, "status poll exceeded client timeout"
        assert status_resp.status_code == 200
        state = status_resp.json().get("status")
        if state in {"completed", "failed"}:
            terminal = status_resp.json()
            break
        time.sleep(0.1)

    assert terminal is not None, "job never reached a terminal state"
    assert terminal["status"] == "completed"
    result = terminal.get("result", {})
    assert {"indexed", "skipped", "errors"} <= set(result)


def test_failed_ingest_reaches_terminal_failed_state(
    client: TestClient,
    valid_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure path (Property 1): when the pipeline raises, the job reaches the
    terminal ``failed`` state carrying an ``error`` message.

    Submit is still fast and returns a job_id; polling reaches ``failed`` with a
    non-empty ``error`` and no single request blocks past the client timeout.
    """

    def raising_ingest_library(self, library_path, library_name=None):
        # Brief sleep so the submit response returns before the job finishes,
        # exercising the queued/running -> failed transition.
        time.sleep(0.2)
        raise RuntimeError("simulated ingest failure")

    monkeypatch.setattr(
        IngestionPipeline, "ingest_library", raising_ingest_library
    )

    start = time.monotonic()
    resp = client.post(
        "/ingest",
        json={"path": str(valid_dir), "name": "lib"},
        headers=_auth_headers(),
    )
    elapsed = time.monotonic() - start

    assert elapsed < CLIENT_TIMEOUT, "submit blocked past the client timeout"
    assert resp.status_code == 200
    job_id = resp.json().get("job_id")
    assert job_id is not None

    # Poll until terminal; every poll must stay well under the client timeout.
    deadline = time.monotonic() + 5.0
    terminal = None
    while time.monotonic() < deadline:
        poll_start = time.monotonic()
        status_resp = client.get(
            f"/ingest/status/{job_id}", headers=_auth_headers()
        )
        assert time.monotonic() - poll_start < CLIENT_TIMEOUT, (
            "status poll exceeded client timeout"
        )
        assert status_resp.status_code == 200
        if status_resp.json().get("status") in {"completed", "failed"}:
            terminal = status_resp.json()
            break
        time.sleep(0.1)

    assert terminal is not None, "job never reached a terminal state"
    assert terminal["status"] == "failed"
    assert terminal.get("error"), "failed job did not surface an error message"
    assert "simulated ingest failure" in terminal["error"]


def test_unknown_status_id_returns_404_on_unfixed_route(
    client: TestClient,
) -> None:
    """GET /ingest/status/<any> returns 404 because the route is absent.

    NOTE: this specific assertion PASSES on unfixed code (404 == missing route),
    which documents the gap the fix fills. It does NOT rescue the module: the
    Property-1 expected-behavior assertions above (fast job_id submit + reachable
    terminal status) still FAIL on unfixed code, so the overall test run fails.
    """
    resp = client.get(
        "/ingest/status/nonexistent-job-id", headers=_auth_headers()
    )
    assert resp.status_code == 404
