"""File system watcher for automatic re-indexing."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from indexer.database import Database
from indexer.pipeline import IngestionPipeline, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class _ReindexHandler(FileSystemEventHandler):
    def __init__(
        self,
        library_path: Path,
        pipeline: IngestionPipeline,
        db: Database,
    ):
        self.library_path = library_path
        self.pipeline = pipeline
        self.db = db
        self._debounce: dict[str, float] = {}
        self._lock = threading.Lock()
        self._debounce_seconds = 2.0

    def _schedule(self, file_path: str) -> None:
        path = Path(file_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        if not path.is_file():
            return

        with self._lock:
            self._debounce[file_path] = time.time()

        def _process() -> None:
            time.sleep(self._debounce_seconds)
            with self._lock:
                scheduled = self._debounce.get(file_path)
                if scheduled is None or time.time() - scheduled < self._debounce_seconds - 0.1:
                    return
                del self._debounce[file_path]

            try:
                library_id = self.db.get_or_create_library(str(self.library_path))
                logger.info("Re-indexing %s", file_path)
                self.pipeline.ingest_file(library_id, Path(file_path))
            except Exception:
                logger.exception("Re-index failed for %s", file_path)

        threading.Thread(target=_process, daemon=True).start()

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)


class LibraryWatcher:
    def __init__(
        self,
        library_path: str | Path,
        pipeline: IngestionPipeline,
        db: Database,
    ):
        self.library_path = Path(library_path).resolve()
        self.pipeline = pipeline
        self.db = db
        self._observer: Observer | None = None

    def start(self) -> None:
        if self._observer:
            return
        handler = _ReindexHandler(self.library_path, self.pipeline, self.db)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.library_path), recursive=True)
        self._observer.start()
        logger.info("Started watching %s", self.library_path)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("Stopped watching %s", self.library_path)
