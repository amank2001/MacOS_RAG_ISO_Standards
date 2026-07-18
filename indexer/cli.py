"""CLI entry point for the ISO Standards Knowledge Base."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from indexer.database import Database
from indexer.embeddings import OllamaClient
from indexer.pipeline import IngestionPipeline
from indexer.rag import RAGService
from indexer.search import SearchService
from indexer.watcher import LibraryWatcher

DEFAULT_DB = Path.home() / "Library" / "Application Support" / "ISOStandardsKB" / "library.db"
DEFAULT_FIGURES = Path.home() / "Library" / "Application Support" / "ISOStandardsKB" / "figures"


def get_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    db_path = Path(args.db) if args.db else DEFAULT_DB
    figures_dir = Path(args.figures) if args.figures else DEFAULT_FIGURES
    return db_path, figures_dir


def cmd_ingest(args: argparse.Namespace) -> None:
    db_path, figures_dir = get_paths(args)
    db = Database(db_path)
    pipeline = IngestionPipeline(db, figures_dir, embed=not args.no_embed)
    stats = pipeline.ingest_library(args.path, args.name)
    print(json.dumps(stats, indent=2))
    db.close()


def cmd_search(args: argparse.Namespace) -> None:
    db_path, _ = get_paths(args)
    db = Database(db_path)
    search = SearchService(db, OllamaClient())
    mode = args.mode
    if mode == "keyword":
        results = search.keyword_search(args.query, args.standard, args.limit)
    elif mode == "semantic":
        results = search.semantic_search(args.query, args.standard, args.limit)
    else:
        results = search.hybrid_search(args.query, args.standard, args.limit)
    print(json.dumps(results, indent=2, default=str))
    db.close()


def cmd_ask(args: argparse.Namespace) -> None:
    db_path, _ = get_paths(args)
    db = Database(db_path)
    rag = RAGService(db)
    result = rag.ask(args.question, args.standard, top_k=args.top_k)
    print(json.dumps(result, indent=2, default=str))
    db.close()


def cmd_watch(args: argparse.Namespace) -> None:
    db_path, figures_dir = get_paths(args)
    db = Database(db_path)
    pipeline = IngestionPipeline(db, figures_dir, embed=not args.no_embed)
    watcher = LibraryWatcher(args.path, pipeline, db)
    print(f"Watching {args.path} for changes... (Ctrl+C to stop)")
    watcher.start()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
    db.close()


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Run the evaluation suite and check for regressions."""
    import sys as _sys

    # Ensure the project root is on sys.path so tests.evaluation can be imported
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in _sys.path:
        _sys.path.insert(0, project_root)

    from tests.evaluation import run_evaluation

    db_path, _ = get_paths(args)

    # Load baseline metrics from JSON file if provided
    baseline = None
    if args.baseline:
        with open(args.baseline, "r", encoding="utf-8") as f:
            baseline = json.load(f)

    dataset_path = args.dataset if args.dataset else None

    results = run_evaluation(db_path, dataset_path=dataset_path, baseline=baseline)

    # If --json flag is set, print raw JSON results to stdout
    if args.json:
        print(json.dumps(results, indent=2, default=str))

    # Exit with code 1 if regressions were detected (for CI integration)
    if results.get("regressions"):
        sys.exit(1)


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn
    from indexer.api import create_app

    db_path, figures_dir = get_paths(args)
    app = create_app(db_path, figures_dir)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="ISO Standards Knowledge Base")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--figures", help="Path to figures storage directory")

    sub = parser.add_subparsers(dest="command", required=True)

    ingest_p = sub.add_parser("ingest", help="Index a folder of ISO documents")
    ingest_p.add_argument("path", help="Folder path to index")
    ingest_p.add_argument("--name", help="Library display name")
    ingest_p.add_argument("--no-embed", action="store_true", help="Skip embedding generation")
    ingest_p.set_defaults(func=cmd_ingest)

    search_p = sub.add_parser("search", help="Search indexed documents")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--standard", help="Filter by standard ID")
    search_p.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    search_p.add_argument("--limit", type=int, default=20)
    search_p.set_defaults(func=cmd_search)

    ask_p = sub.add_parser("ask", help="Ask a grounded question")
    ask_p.add_argument("question", help="Question to ask")
    ask_p.add_argument("--standard", help="Filter by standard ID")
    ask_p.add_argument("--top-k", type=int, default=12)
    ask_p.set_defaults(func=cmd_ask)

    watch_p = sub.add_parser("watch", help="Watch folder and re-index on changes")
    watch_p.add_argument("path", help="Folder path to watch")
    watch_p.add_argument("--no-embed", action="store_true")
    watch_p.set_defaults(func=cmd_watch)

    serve_p = sub.add_parser("serve", help="Start local API server for macOS app")
    serve_p.add_argument("--port", type=int, default=8742)
    serve_p.set_defaults(func=cmd_serve)

    eval_p = sub.add_parser("evaluate", help="Run evaluation suite and check for regressions")
    eval_p.add_argument("--dataset", help="Path to custom eval dataset JSON")
    eval_p.add_argument("--baseline", help="Path to baseline metrics JSON for regression detection")
    eval_p.add_argument("--json", action="store_true", help="Output raw JSON results")
    eval_p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
