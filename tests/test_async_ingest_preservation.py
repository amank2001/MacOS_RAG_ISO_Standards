"""Preservation property tests for the async-ingest-job bugfix spec.

Property 2: Preservation - Non-buggy inputs and other endpoints behave
identically after the fix.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 2.5**

METHODOLOGY (observation-first): the behaviors asserted here were first observed
on the UNFIXED code and recorded as the baseline that MUST be preserved after
the async submit/poll fix lands. See ``docs`` block below for the exact recorded
observations.

Recorded baseline observations (UNFIXED code, empty DB, no Ollama available):
  - POST /ingest on a 2-file docx fixture -> 200 {indexed: 2, skipped: 0,
    errors: 0} (plus a "files" list). Re-submitting the same folder ->
    {indexed: 0, skipped: 2, errors: 0}. (Requirement 3.1)
  - POST /ingest with no_embed=True -> no rows in chunk_embeddings.
    (Requirement 3.5)
  - POST /ingest on a non-directory path -> 400 "Not a directory: <path>".
    (Requirement 2.5)
  - POST /ingest / protected routes without a valid Bearer token -> 401
    Unauthorized (missing OR wrong token). (Requirement 3.3)
  - GET /health -> 200 with NO auth. GET /libraries, GET /documents,
    POST /search, POST /ask -> 200 with auth, 401 without. POST /watch/start ->
    {status: watching} then {status: already_watching}; POST /watch/stop ->
    {status: stopped} / {status: not_found}. DELETE /libraries/{id} and
    /documents/{id} for missing ids -> 404. (Requirements 3.4, 3.2)
  - GET /ingest/status/<random> -> 404 (route absent on unfixed code; must stay
    404 for UNKNOWN ids after the fix). (documented preservation expectation)

CONTRACT ADAPTATION: preservation of the *result counts* must hold across the
contract change. ``ingest_counts`` below understands BOTH the current
synchronous contract (counts returned inline from POST /ingest) and the future
async contract (POST /ingest returns {job_id, status}; counts are read from
GET /ingest/status/{job_id}). This lets the count-preservation assertions pass
now AND after the fix without editing the test.

FIX-DEPENDENT ASSERTIONS (the status endpoint and job-id submit response) were
isolated into xfail tests until the fix landed. Now that the async submit/poll
fix is implemented they are ENABLED as regular tests and must PASS.
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from indexer import auth
from indexer.api import _ingest_executor, create_app
from indexer.database import Database
from indexer.pipeline import IngestionPipeline
from tests.create_fixtures import create_sample_docx

TOKEN = "test-token-preservation"

# Recorded baseline counts for the canonical 2-file docx fixture (observed on
# UNFIXED code). Preserved as an explicit example alongside the property tests.
FIXTURE_TWO_FILE_COUNTS = {"indexed": 2, "skipped": 0, "errors": 0}

# Terminal states for the (post-fix) async job status.
_TERMINAL = {"completed", "failed"}
# Poll budget for the async contract; each poll is a fast local read.
_POLL_TIMEOUT = 15.0


def _auth_headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_app_dir() -> tuple[Path, Path]:
    """Create a fresh (db_path, figures_dir) pair under a temp directory."""
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "test.db"
    figures_dir = tmp / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    return db_path, figures_dir


def _make_client() -> tuple[TestClient, Path]:
    """Build a fresh FastAPI app + TestClient. Returns (client, db_path)."""
    auth._current_token = TOKEN
    db_path, figures_dir = _make_app_dir()
    app = create_app(db_path=db_path, figures_dir=figures_dir)
    return TestClient(app), db_path


def _make_fixture(num_files: int, prefix: str = "ISO") -> Path:
    """Create a temp folder containing ``num_files`` sample docx documents."""
    folder = Path(tempfile.mkdtemp())
    for i in range(num_files):
        create_sample_docx(folder, f"{prefix}_{i}.docx")
    return folder


def ingest_counts(
    client: TestClient,
    path: Path,
    name: str | None = None,
    no_embed: bool = False,
) -> dict:
    """Submit POST /ingest and return {indexed, skipped, errors} counts.

    Understands both contracts:
      - UNFIXED (synchronous): counts are returned inline from POST /ingest.
      - FIXED (async): POST /ingest returns {job_id, status}; poll
        GET /ingest/status/{job_id} until a terminal state and read result.
    """
    payload: dict = {"path": str(path)}
    if name is not None:
        payload["name"] = name
    if no_embed:
        payload["no_embed"] = True

    resp = client.post("/ingest", json=payload, headers=_auth_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()

    if "job_id" in body:  # async contract (after fix)
        job_id = body["job_id"]
        deadline = time.monotonic() + _POLL_TIMEOUT
        while time.monotonic() < deadline:
            status_resp = client.get(
                f"/ingest/status/{job_id}", headers=_auth_headers()
            )
            assert status_resp.status_code == 200, status_resp.text
            data = status_resp.json()
            if data.get("status") in _TERMINAL:
                assert data["status"] == "completed", data
                return data.get("result") or {}
            time.sleep(0.05)
        raise AssertionError("async ingest job never reached a terminal state")

    return body  # synchronous contract (unfixed)


def _sync_pipeline_counts(fixture: Path) -> dict:
    """Ground truth: run IngestionPipeline.ingest_library directly on a fixture.

    Uses a throwaway DB so it does not interfere with the app under test.
    Counts (indexed/skipped/errors) are independent of embedding, so Ollama
    availability does not affect the comparison.
    """
    db_path, figures_dir = _make_app_dir()
    db = Database(db_path)
    try:
        pipeline = IngestionPipeline(db, figures_dir, embed=False)
        return pipeline.ingest_library(fixture, "ground-truth")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pytest fixtures for the deterministic example tests.
# ---------------------------------------------------------------------------
@pytest.fixture
def client() -> TestClient:
    c, _ = _make_client()
    return c


@pytest.fixture(autouse=True)
def _drain_ingest_executor() -> None:
    """Keep the shared single-worker ingest executor isolated between tests.

    After the fix, ``POST /ingest`` fire-and-forgets jobs onto a module-level
    single-worker ``ThreadPoolExecutor``. Some tests here submit jobs without
    polling to completion, so those jobs may still be running/queued when the
    next test starts. Because the worker is shared and serial, that backlog
    could starve a later test's job. After each test we enqueue a sentinel and
    wait for it: since the queue is FIFO on one worker, the sentinel only
    completes once every previously submitted job has finished, guaranteeing an
    idle worker for the next test. Mirrors the pattern in tests/test_async_ingest.py.
    """
    yield
    _ingest_executor.submit(lambda: None).result(timeout=60)


# ===========================================================================
# Requirement 3.1 - fast-folder result counts preserved
# ===========================================================================
def test_fast_fixture_counts_match_recorded_baseline(client: TestClient) -> None:
    """A 2-file fixture yields the recorded baseline {indexed:2, skipped:0,
    errors:0} (Requirement 3.1). PASSES now on the synchronous contract."""
    fixture = _make_fixture(2)
    counts = ingest_counts(client, fixture, name="lib")
    for key, expected in FIXTURE_TWO_FILE_COUNTS.items():
        assert counts.get(key) == expected, (key, counts)


def test_reingest_same_folder_skips(client: TestClient) -> None:
    """Re-submitting an already-indexed folder skips every file (Requirement
    3.1). Baseline observation: {indexed:0, skipped:2, errors:0}."""
    fixture = _make_fixture(2)
    first = ingest_counts(client, fixture, name="lib")
    assert first.get("indexed") == 2
    second = ingest_counts(client, fixture, name="lib")
    assert second.get("indexed") == 0
    assert second.get("skipped") == 2
    assert second.get("errors") == 0


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(num_files=st.integers(min_value=1, max_value=3))
def test_fast_fixture_counts_equal_sync_pipeline(num_files: int) -> None:
    """For randomized fast fixtures, the counts observed through POST /ingest
    equal the synchronous pipeline's counts for the same input (Requirement
    3.1). Works under both the sync (now) and async (post-fix) contracts."""
    client, _ = _make_client()
    fixture = _make_fixture(num_files)

    expected = _sync_pipeline_counts(fixture)
    observed = ingest_counts(client, fixture, name="lib")

    for key in ("indexed", "skipped", "errors"):
        assert observed.get(key) == expected.get(key), (
            f"{key}: observed={observed.get(key)} expected={expected.get(key)}"
        )
    assert observed.get("indexed") == num_files


# ===========================================================================
# Requirement 3.5 - no_embed honored (no embeddings generated)
# ===========================================================================
def test_no_embed_generates_no_embeddings() -> None:
    """no_embed=True skips embedding generation (Requirement 3.5).

    Baseline observation: zero rows in chunk_embeddings after a no_embed ingest.
    """
    client, db_path = _make_client()
    fixture = _make_fixture(1)
    counts = ingest_counts(client, fixture, name="lib", no_embed=True)
    assert counts.get("indexed") == 1

    conn = sqlite3.connect(str(db_path))
    try:
        n = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    finally:
        conn.close()
    assert n == 0, f"no_embed=True still produced {n} embeddings"


# ===========================================================================
# Requirement 2.5 - not-a-directory error surfaced at submit time
# ===========================================================================
def test_not_a_directory_returns_400(client: TestClient) -> None:
    """Submitting a non-directory path returns the surfaced 400 'Not a
    directory' error (Requirement 2.5)."""
    missing = Path(tempfile.mkdtemp()) / "does-not-exist"
    resp = client.post(
        "/ingest",
        json={"path": str(missing), "name": "x"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert "Not a directory" in resp.json()["detail"]


# ===========================================================================
# Requirement 3.3 - Bearer auth enforced on POST /ingest
# ===========================================================================
def test_ingest_requires_auth_missing_and_wrong(client: TestClient) -> None:
    """POST /ingest without a valid Bearer token is rejected with 401
    (Requirement 3.3)."""
    fixture = _make_fixture(1)
    payload = {"path": str(fixture), "name": "lib"}

    no_token = client.post("/ingest", json=payload)
    assert no_token.status_code == 401

    wrong_token = client.post(
        "/ingest", json=payload, headers=_auth_headers("not-the-token")
    )
    assert wrong_token.status_code == 401


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    token=st.one_of(
        st.none(),
        # Constrain to visible ASCII so values are valid HTTP header content.
        st.text(
            alphabet=st.characters(min_codepoint=33, max_codepoint=126),
            max_size=40,
        ),
        st.sampled_from(["", "Bearer", "wrong-token"]),
    )
)
def test_ingest_auth_enforced_across_random_tokens(token) -> None:
    """Across randomized missing/invalid tokens, POST /ingest is always
    rejected with 401 (Requirement 3.3). Uses a folder path that WOULD be valid
    so the rejection is purely about auth, not path validation."""
    assume(token != TOKEN)
    client, _ = _make_client()
    fixture = _make_fixture(1)
    payload = {"path": str(fixture), "name": "lib"}

    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    resp = client.post("/ingest", json=payload, headers=headers)
    assert resp.status_code == 401, (token, resp.status_code)


# ===========================================================================
# Requirement 3.4 (+ 3.2 watch endpoints) - other endpoints unchanged
# ===========================================================================
# Endpoint contract observed on the UNFIXED code (empty DB). Each tuple:
# (method, path, json_body, expected_status_with_valid_auth).
_ENDPOINT_CONTRACT = [
    ("GET", "/health", None, 200),
    ("GET", "/libraries", None, 200),
    ("GET", "/documents", None, 200),
    ("POST", "/search", {"query": "scope"}, 200),
    ("POST", "/ask", {"question": "what is scope?"}, 200),
    ("DELETE", "/libraries/999999", None, 404),
    ("DELETE", "/documents/999999", None, 404),
]

# Protected endpoints that must return 401 without a valid token. /health is
# intentionally excluded because it is public.
_PROTECTED_CONTRACT = [t for t in _ENDPOINT_CONTRACT if t[1] != "/health"]


def _call(client: TestClient, method: str, path: str, body, headers):
    if method == "GET":
        return client.get(path, headers=headers)
    if method == "POST":
        return client.post(path, json=body, headers=headers)
    if method == "DELETE":
        return client.delete(path, headers=headers)
    raise ValueError(method)


@settings(
    max_examples=len(_ENDPOINT_CONTRACT) * 2,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(spec=st.sampled_from(_ENDPOINT_CONTRACT))
def test_other_endpoints_contract_with_auth(spec) -> None:
    """For randomized non-ingest requests, authenticated responses match the
    pre-fix contract (Requirement 3.4)."""
    client, _ = _make_client()
    method, path, body, expected = spec
    resp = _call(client, method, path, body, _auth_headers())
    assert resp.status_code == expected, (method, path, resp.status_code)


@settings(
    max_examples=len(_PROTECTED_CONTRACT) * 3,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(
    spec=st.sampled_from(_PROTECTED_CONTRACT),
    token=st.one_of(
        st.none(),
        st.text(
            alphabet=st.characters(min_codepoint=33, max_codepoint=126),
            max_size=30,
        ),
    ),
)
def test_other_protected_endpoints_require_auth(spec, token) -> None:
    """Protected non-ingest endpoints reject missing/invalid tokens with 401
    (Requirement 3.3/3.4). /health stays public and is excluded."""
    assume(token != TOKEN)
    client, _ = _make_client()
    method, path, body, _expected = spec
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    resp = _call(client, method, path, body, headers)
    assert resp.status_code == 401, (method, path, token, resp.status_code)


def test_health_is_public(client: TestClient) -> None:
    """GET /health responds 200 with no auth (Requirement 3.4)."""
    assert client.get("/health").status_code == 200


def test_watch_start_stop_lifecycle(client: TestClient) -> None:
    """Watch endpoints behave as before: start -> watching, repeat ->
    already_watching, stop -> stopped, stop-unknown -> not_found (backend side
    of Requirement 3.2 / 3.4)."""
    wdir = Path(tempfile.mkdtemp())
    start = client.post("/watch/start", json={"path": str(wdir)}, headers=_auth_headers())
    assert start.status_code == 200
    assert start.json()["status"] == "watching"

    again = client.post("/watch/start", json={"path": str(wdir)}, headers=_auth_headers())
    assert again.json()["status"] == "already_watching"

    stop = client.post("/watch/stop", json={"path": str(wdir)}, headers=_auth_headers())
    assert stop.json()["status"] == "stopped"

    unknown = client.post(
        "/watch/stop",
        json={"path": str(Path(tempfile.mkdtemp()) / "never")},
        headers=_auth_headers(),
    )
    assert unknown.json()["status"] == "not_found"


def test_watch_start_requires_auth(client: TestClient) -> None:
    """POST /watch/start without auth is rejected (Requirement 3.3/3.4)."""
    wdir = Path(tempfile.mkdtemp())
    assert client.post("/watch/start", json={"path": str(wdir)}).status_code == 401


# ===========================================================================
# Unknown-job-id preservation expectation.
# ===========================================================================
def test_unknown_job_id_returns_404(client: TestClient) -> None:
    """GET /ingest/status/<random> returns 404.

    PASSES now (route is absent on unfixed code -> 404) and MUST keep returning
    404 for UNKNOWN ids after the fix. Documented preservation expectation.
    """
    resp = client.get("/ingest/status/nonexistent-job-id", headers=_auth_headers())
    assert resp.status_code == 404


# ===========================================================================
# FIX-DEPENDENT assertions - now ENABLED (the fix has landed).
# These depend on routes/response shapes introduced by the async fix (the
# status endpoint and the job-id submit response). They were xfail'd until the
# fix landed (tasks 3.2/3.3); now that POST /ingest returns {job_id, status}
# and GET /ingest/status/{job_id} exists on the protected router, they must PASS.
# ===========================================================================
def test_submit_returns_job_id_after_fix(client: TestClient) -> None:
    """POST /ingest returns the async submit contract {job_id, status} with a
    non-terminal starting status (Requirement 2.1, task 3.2)."""
    fixture = _make_fixture(1)
    resp = client.post(
        "/ingest", json={"path": str(fixture), "name": "lib"}, headers=_auth_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body.get("status") in {"queued", "running"}


def test_status_route_requires_auth_after_fix(client: TestClient) -> None:
    """The status route enforces Bearer auth like other protected routes
    (Requirement 3.3, task 3.3). A request with no token must be 401 (not 404),
    proving the route is registered on the protected router."""
    fixture = _make_fixture(1)
    submit = client.post(
        "/ingest", json={"path": str(fixture), "name": "lib"}, headers=_auth_headers()
    )
    job_id = submit.json().get("job_id", "any-id")
    # No token -> must be 401 (not 404) because the protected route exists.
    resp = client.get(f"/ingest/status/{job_id}")
    assert resp.status_code == 401
