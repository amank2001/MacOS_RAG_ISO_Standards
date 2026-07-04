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
        watcher = watchers.pop(path, None)
        if watcher:
            watcher.stop()
            return {"status": "stopped", "path": path}
        return {"status": "not_found", "path": path}

    return app
