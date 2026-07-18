"""FastAPI server for the macOS app."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from indexer.auth import verify_token
from indexer.database import Database
from indexer.embeddings import OllamaClient
from indexer.pipeline import IngestionPipeline
from indexer.rag import RAGService
from indexer.search import SearchService
from indexer.watcher import LibraryWatcher


# Single-worker executor to run ingestion jobs off the event loop. A single
# worker naturally serializes ingest jobs, matching the prior one-at-a-time
# synchronous behavior.
_ingest_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest-job")


class IngestRequest(BaseModel):
    path: str
    name: str | None = None
    no_embed: bool = False


class SearchRequest(BaseModel):
    query: str
    standard_id: str | None = None
    mode: str = "hybrid"
    limit: int = 20


class AskRequest(BaseModel):
    question: str = Field(..., max_length=2000)
    standard_id: str | None = None
    top_k: int = Field(default=12, le=50)


class WatchRequest(BaseModel):
    path: str
    no_embed: bool = False


def create_app(db_path: Path, figures_dir: Path) -> FastAPI:
    app = FastAPI(title="ISO Standards KB API", version="0.1.0")

    # No CORS middleware — this is a local-only app where the Swift client
    # communicates via direct HTTP on 127.0.0.1, not through a browser.

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": exc.errors()},
        )

    watchers: dict[str, LibraryWatcher] = {}

    # In-memory ingestion job registry keyed by job_id. Each entry holds the
    # job's lifecycle state, its final result (on completion), an error message
    # (on failure), and the submission time. State transitions:
    #   queued -> running -> completed | failed
    # The lock guards every mutation of ``jobs`` so the background worker and
    # request threads do not race.
    jobs: dict[str, dict[str, Any]] = {}
    jobs_lock = threading.Lock()

    def get_db() -> Database:
        return Database(db_path)

    def _run_ingest_job(
        job_id: str, path: Path, name: str | None, no_embed: bool
    ) -> None:
        """Run an ingestion job on a background worker.

        Uses its own fresh ``Database`` connection (never the request-scoped
        ``get_db()`` connection, which must not be shared across threads).
        Records the pipeline result on success or the error message on failure,
        and always closes the job's DB connection.
        """
        with jobs_lock:
            job = jobs.get(job_id)
            if job is not None:
                job["state"] = "running"

        db = Database(db_path)
        try:
            pipeline = IngestionPipeline(db, figures_dir, embed=not no_embed)
            result = pipeline.ingest_library(path, name)
            with jobs_lock:
                job = jobs.get(job_id)
                if job is not None:
                    job["result"] = result
                    job["state"] = "completed"
        except Exception as exc:  # noqa: BLE001
            with jobs_lock:
                job = jobs.get(job_id)
                if job is not None:
                    job["error"] = str(exc)
                    job["state"] = "failed"
        finally:
            db.close()

    def _prune_terminal_jobs(max_age_seconds: float = 3600.0) -> None:
        """Drop terminal (completed/failed) jobs older than ``max_age_seconds``.

        In-flight jobs (``queued``/``running``) are never pruned regardless of
        age, so a long-running ingest is never dropped from the registry. Must
        be called with ``jobs`` mutated under ``jobs_lock``.
        """
        cutoff = time.time() - max_age_seconds
        with jobs_lock:
            stale = [
                job_id
                for job_id, job in jobs.items()
                if job["state"] in ("completed", "failed")
                and job["created_at"] < cutoff
            ]
            for job_id in stale:
                del jobs[job_id]

    def _stop_watcher(path: str) -> str | None:
        """Stop and drop the watcher for ``path``.

        Returns an error message describing the stop failure, or ``None`` when
        the watcher was stopped cleanly or was not registered in the first
        place.
        """
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
        """Best-effort removal of figure image files.

        Missing files are treated as already cleaned up. ``OSError`` failures
        are collected as ``{"image_path": ..., "error": ...}`` entries so the
        caller can surface them without aborting the wider deletion.
        """
        errors: list[dict[str, str]] = []
        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError as exc:
                errors.append({"image_path": p, "error": str(exc)})
        return errors

    # --- Health endpoint (no auth required) ---
    @app.get("/health")
    def health() -> dict[str, Any]:
        ollama = OllamaClient()
        return {
            "status": "ok",
            "ollama_available": ollama.is_available(),
            "db_path": str(db_path),
        }

    # --- Protected routes (require valid Bearer token) ---
    protected = APIRouter(dependencies=[Depends(verify_token)])

    @protected.get("/libraries")
    def list_libraries() -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.list_libraries()
        finally:
            db.close()

    @protected.get("/documents")
    def list_documents(library_id: int | None = None) -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.list_documents(library_id)
        finally:
            db.close()

    @protected.get("/documents/{document_id}/clauses")
    def list_clauses(document_id: int) -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.list_clauses(document_id)
        finally:
            db.close()

    @protected.get("/documents/{document_id}/figures")
    def list_figures(document_id: int) -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.get_figures_for_document(document_id)
        finally:
            db.close()

    @protected.post("/ingest")
    def ingest(req: IngestRequest) -> dict[str, Any]:
        # Validate the directory at submit time so an invalid path is rejected
        # fast and surfaced directly to the client (Requirement 2.5).
        path = Path(req.path)
        if not path.is_dir():
            raise HTTPException(400, f"Not a directory: {req.path}")

        # Bound registry memory by dropping old terminal jobs; in-flight jobs
        # are preserved.
        _prune_terminal_jobs()

        job_id = uuid4().hex
        with jobs_lock:
            jobs[job_id] = {
                "state": "queued",
                "result": None,
                "error": None,
                "created_at": time.time(),
            }

        _ingest_executor.submit(
            _run_ingest_job, job_id, path, req.name, req.no_embed
        )

        return {"job_id": job_id, "status": "queued"}

    @protected.get("/ingest/status/{job_id}")
    def ingest_status(job_id: str) -> dict[str, Any]:
        # Read a snapshot of the job entry under the lock, then build the
        # response outside the lock. An unknown id yields a 404.
        with jobs_lock:
            job = jobs.get(job_id)
            if job is None:
                raise HTTPException(404, f"Unknown job: {job_id}")
            state = job["state"]
            result = job["result"]
            error = job["error"]

        response: dict[str, Any] = {"job_id": job_id, "status": state}
        if state == "completed":
            response["result"] = result
        elif state == "failed":
            response["error"] = error
        return response

    @protected.post("/search")
    def search(req: SearchRequest) -> list[dict[str, Any]]:
        db = get_db()
        try:
            svc = SearchService(db, OllamaClient())
            if req.mode == "keyword":
                results = svc.keyword_search(req.query, req.standard_id, req.limit)
            elif req.mode == "semantic":
                results = svc.semantic_search(req.query, req.standard_id, req.limit)
            else:
                results = svc.hybrid_search(req.query, req.standard_id, req.limit)
            # Return file_path unchanged (absolute DB path), matching the
            # /documents endpoint. This is a local-only app (127.0.0.1, same
            # user) whose Swift client opens documents by absolute file_path.
            return results
        finally:
            db.close()

    @protected.post("/ask")
    def ask(req: AskRequest) -> dict[str, Any]:
        db = get_db()
        try:
            rag = RAGService(db)
            return rag.ask(req.question, req.standard_id, req.top_k)
        finally:
            db.close()

    @protected.post("/watch/start")
    def start_watch(req: WatchRequest) -> dict[str, str]:
        path = str(Path(req.path).resolve())
        if path in watchers:
            return {"status": "already_watching", "path": path}
        db = get_db()
        pipeline = IngestionPipeline(db, figures_dir, embed=not req.no_embed)
        watcher = LibraryWatcher(path, pipeline, db)
        watcher.start()
        watchers[path] = watcher
        return {"status": "watching", "path": path}

    @protected.post("/watch/stop")
    def stop_watch(req: WatchRequest) -> dict[str, str]:
        path = str(Path(req.path).resolve())
        if path not in watchers:
            return {"status": "not_found", "path": path}
        _stop_watcher(req.path)
        return {"status": "stopped", "path": path}

    @protected.delete("/libraries/{library_id}")
    def delete_library(library_id: int) -> dict[str, Any]:
        db = get_db()
        try:
            lib = db.get_library(library_id)
            if lib is None:
                raise HTTPException(404, f"Library {library_id} not found")

            # Stop the watcher first so it isn't observing a library that is
            # about to disappear. Any stop failure is captured and surfaced in
            # the response, but figure cleanup and row deletion still proceed.
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

    @protected.delete("/documents/{document_id}")
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

    app.include_router(protected)

    return app
