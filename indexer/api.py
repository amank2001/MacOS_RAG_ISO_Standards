"""FastAPI server for the macOS app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from indexer.database import Database
from indexer.embeddings import OllamaClient
from indexer.pipeline import IngestionPipeline
from indexer.rag import RAGService
from indexer.search import SearchService
from indexer.watcher import LibraryWatcher


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
    question: str
    standard_id: str | None = None
    top_k: int = 12


class WatchRequest(BaseModel):
    path: str
    no_embed: bool = False


def create_app(db_path: Path, figures_dir: Path) -> FastAPI:
    app = FastAPI(title="ISO Standards KB API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    watchers: dict[str, LibraryWatcher] = {}

    def get_db() -> Database:
        return Database(db_path)

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

    @app.get("/health")
    def health() -> dict[str, Any]:
        ollama = OllamaClient()
        return {
            "status": "ok",
            "ollama_available": ollama.is_available(),
            "db_path": str(db_path),
        }

    @app.get("/libraries")
    def list_libraries() -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.list_libraries()
        finally:
            db.close()

    @app.get("/documents")
    def list_documents(library_id: int | None = None) -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.list_documents(library_id)
        finally:
            db.close()

    @app.get("/documents/{document_id}/clauses")
    def list_clauses(document_id: int) -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.list_clauses(document_id)
        finally:
            db.close()

    @app.get("/documents/{document_id}/figures")
    def list_figures(document_id: int) -> list[dict[str, Any]]:
        db = get_db()
        try:
            return db.get_figures_for_document(document_id)
        finally:
            db.close()

    @app.post("/ingest")
    def ingest(req: IngestRequest) -> dict[str, Any]:
        path = Path(req.path)
        if not path.is_dir():
            raise HTTPException(400, f"Not a directory: {req.path}")
        db = get_db()
        try:
            pipeline = IngestionPipeline(db, figures_dir, embed=not req.no_embed)
            return pipeline.ingest_library(path, req.name)
        finally:
            db.close()

    @app.post("/search")
    def search(req: SearchRequest) -> list[dict[str, Any]]:
        db = get_db()
        try:
            svc = SearchService(db, OllamaClient())
            if req.mode == "keyword":
                return svc.keyword_search(req.query, req.standard_id, req.limit)
            if req.mode == "semantic":
                return svc.semantic_search(req.query, req.standard_id, req.limit)
            return svc.hybrid_search(req.query, req.standard_id, req.limit)
        finally:
            db.close()

    @app.post("/ask")
    def ask(req: AskRequest) -> dict[str, Any]:
        db = get_db()
        try:
            rag = RAGService(db)
            return rag.ask(req.question, req.standard_id, req.top_k)
        finally:
            db.close()

    @app.post("/watch/start")
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

    @app.post("/watch/stop")
    def stop_watch(req: WatchRequest) -> dict[str, str]:
        path = str(Path(req.path).resolve())
        if path not in watchers:
            return {"status": "not_found", "path": path}
        _stop_watcher(req.path)
        return {"status": "stopped", "path": path}

    @app.delete("/libraries/{library_id}")
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

    return app
