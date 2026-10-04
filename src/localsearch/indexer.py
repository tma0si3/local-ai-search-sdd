"""Orchestrates an indexing run: scan → extract → chunk → embed → store.

The only module that coordinates the others; the others do not know about each other
(Principle VI). Runs happen on a background thread so the UI can report progress (FR-012).

Two rules shape everything here:

1. **A per-document failure never stops the run** (FR-011). It is recorded with a reason
   and the run continues. A single unreadable PDF must not cost the user the other 499.
2. **A document yielding no text is ``skipped``, never ``indexed`` with zero chunks**
   (data-model.md). Otherwise the counts lie.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import embed, store
from .chunk import chunk_text
from .errors import ExtractionError, NotConfiguredError
from .extract import extract_text, file_type_of

# Embedding in batches keeps peak memory bounded on large documents.
_EMBED_BATCH = 64


@dataclass
class ScannedFile:
    path: Path
    name: str
    relative_path: str
    file_type: str
    size_bytes: int
    modified_at: str


def scan_folder(folder: Path) -> list[ScannedFile]:
    """Find supported documents at any depth below ``folder`` (FR-003).

    Hidden files and directories are skipped: ``.git``, ``node_modules``, and macOS
    resource forks are noise, not documents the user means to search.
    """
    found: list[ScannedFile] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(folder).parts):
            continue
        file_type = file_type_of(path)
        if file_type is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append(
            ScannedFile(
                path=path,
                name=path.name,
                relative_path=str(path.relative_to(folder)),
                file_type=file_type,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(
                    timespec="seconds"
                ),
            )
        )
    return found


@dataclass
class IndexingState:
    """In-memory run state. Not persisted — a run does not survive a restart."""

    state: str = "idle"  # idle | running | completed | failed
    trigger: str | None = None  # manual | watch
    current_file: str | None = None
    processed: int = 0
    total: int = 0
    rerun_pending: bool = False
    index_stale: bool = False
    errors: list[dict[str, str]] = field(default_factory=list)
    documents_found: int | None = None
    documents_indexed: int | None = None
    documents_skipped: int | None = None
    chunk_count: int | None = None
    message: str | None = None

    def as_dict(self) -> dict:
        payload = {
            "state": self.state,
            "trigger": self.trigger,
            "current_file": self.current_file,
            "processed": self.processed,
            "total": self.total,
            "rerun_pending": self.rerun_pending,
            "index_stale": self.index_stale,
            "errors": self.errors,
        }
        if self.state == "completed":
            payload.update(
                documents_found=self.documents_found,
                documents_indexed=self.documents_indexed,
                documents_skipped=self.documents_skipped,
                chunk_count=self.chunk_count,
            )
        if self.message:
            payload["message"] = self.message
        return payload


class Indexer:
    """Owns the run state and the single-run guard.

    A request arriving mid-run is *queued*, never refused, and at most one run is ever
    pending however many requests arrive (FR-032). Manual and automatic triggers behave
    identically — the same situation should not have two behaviours.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state = IndexingState()

    def snapshot(self) -> dict:
        with self._lock:
            return self.state.as_dict()

    def is_running(self) -> bool:
        with self._lock:
            return self.state.state == "running"

    def mark_stale(self, stale: bool) -> None:
        with self._lock:
            self.state.index_stale = stale

    def request_run(self, folder: Path | None, trigger: str = "manual") -> dict:
        """Start a run, or queue one if a run is already active."""
        if folder is None:
            raise NotConfiguredError(
                "No documents folder is configured. Set one before indexing."
            )

        with self._lock:
            if self.state.state == "running":
                self.state.rerun_pending = True
                return {"state": "running", "rerun_pending": True}

            self.state = IndexingState(
                state="running", trigger=trigger, total=0, processed=0
            )
            self._thread = threading.Thread(
                target=self._run_until_settled, args=(folder, trigger), daemon=True
            )
            self._thread.start()
            return {"state": "running", "rerun_pending": False}

    def _run_until_settled(self, folder: Path, trigger: str) -> None:
        """Run, then run once more if changes arrived meanwhile — but only once more.

        The loop is what prevents an endless rebuild on a continuously changing folder:
        however many triggers arrive during a run, they collapse into a single follow-up.
        """
        while True:
            try:
                self._execute(folder)
            except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
                with self._lock:
                    self.state.state = "failed"
                    self.state.current_file = None
                    self.state.message = (
                        f"Indexing stopped: {exc}. Your previous index, if any, is "
                        "unchanged and still searchable."
                    )
                return

            with self._lock:
                if not self.state.rerun_pending:
                    return
                self.state = IndexingState(state="running", trigger=trigger)

    def _execute(self, folder: Path) -> None:
        files = scan_folder(folder)

        with self._lock:
            self.state.total = len(files)
            self.state.index_stale = False

        with store.IndexBuilder(str(folder), embed.model_name()) as builder:
            for scanned in files:
                with self._lock:
                    self.state.current_file = scanned.relative_path

                self._process_one(builder, scanned)

                with self._lock:
                    self.state.processed += 1

            meta = builder.commit()

        with self._lock:
            self.state.state = "completed"
            self.state.current_file = None
            self.state.index_stale = False
            self.state.documents_found = meta.documents_found
            self.state.documents_indexed = meta.documents_indexed
            self.state.documents_skipped = meta.documents_skipped
            self.state.chunk_count = meta.chunk_count

    def _process_one(self, builder: store.IndexBuilder, scanned: ScannedFile) -> None:
        """Index one document, or record why it was skipped.

        Only *per-document* problems are caught here. A failure of the embedding model is
        not a property of the document — if it were swallowed, every document would be
        recorded as skipped and the run would commit an empty index reported as success.
        Infrastructure failures therefore propagate and fail the whole run, leaving the
        previous index intact.
        """
        common = {
            "path": str(scanned.path),
            "name": scanned.name,
            "relative_path": scanned.relative_path,
            "file_type": scanned.file_type,
            "size_bytes": scanned.size_bytes,
            "modified_at": scanned.modified_at,
        }

        try:
            text = extract_text(scanned.path)
            chunks = chunk_text(text)
            if not chunks:
                raise ExtractionError(
                    "This file contains no text once read, so there is nothing to search."
                )
        except ExtractionError as exc:
            self._record_skip(builder, common, exc.message)
            return
        except OSError as exc:
            self._record_skip(builder, common, f"This file could not be read: {exc}")
            return

        # Outside the try: an embedding or storage failure is fatal to the run, by design.
        vectors = self._embed_in_batches([c.text for c in chunks])
        builder.add_indexed(**common, chunks=chunks, vectors=vectors)

    def _record_skip(self, builder: store.IndexBuilder, common: dict, reason: str) -> None:
        builder.add_skipped(**common, reason=reason)
        with self._lock:
            self.state.errors.append({"name": common["relative_path"], "reason": reason})

    @staticmethod
    def _embed_in_batches(texts: list[str]):
        import numpy as np

        batches = [
            embed.embed_texts(texts[start : start + _EMBED_BATCH])
            for start in range(0, len(texts), _EMBED_BATCH)
        ]
        return np.vstack(batches)


indexer = Indexer()
