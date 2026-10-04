"""Index persistence: SQLite for text and metadata, a NumPy matrix for vectors.

This is the only module in the project that imports ``sqlite3`` (data-model.md, module
ownership). Everything else goes through these functions.

The database and the matrix are written and replaced **as a pair**. A chunk's
``embedding_row`` is an index into the matrix, so a mismatched pair is a corrupt index.
Builds therefore go to temporary files and are swapped in only once the run has finished,
which is what stops an interrupted run from destroying a working index (research.md §7).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .config import database_path, embeddings_path

SCHEMA = """
CREATE TABLE documents (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    file_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    modified_at   TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('indexed', 'skipped')),
    skip_reason   TEXT,
    CHECK (status = 'indexed' OR (skip_reason IS NOT NULL AND skip_reason != ''))
);

CREATE TABLE chunks (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal       INTEGER NOT NULL,
    text          TEXT NOT NULL CHECK (text != ''),
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    embedding_row INTEGER NOT NULL UNIQUE,
    UNIQUE (document_id, ordinal),
    CHECK (char_start < char_end)
);

CREATE INDEX idx_chunks_embedding_row ON chunks(embedding_row);

-- One row, written only on successful completion. Its presence is what makes an index
-- "complete"; its absence is how an interrupted run is detected.
CREATE TABLE index_meta (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    folder_path        TEXT NOT NULL,
    built_at           TEXT NOT NULL,
    embedding_model    TEXT NOT NULL,
    chunk_count        INTEGER NOT NULL,
    documents_found    INTEGER NOT NULL,
    documents_indexed  INTEGER NOT NULL,
    documents_skipped  INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class IndexMeta:
    folder_path: str
    built_at: str
    embedding_model: str
    chunk_count: int
    documents_found: int
    documents_indexed: int
    documents_skipped: int


@dataclass(frozen=True)
class ChunkRecord:
    """A chunk joined to its document, as returned for a search hit."""

    text: str
    char_start: int
    char_end: int
    document_name: str
    document_relative_path: str
    document_path: str


@dataclass(frozen=True)
class DocumentFingerprint:
    """The three fields reconciliation compares. Deliberately metadata only (FR-035)."""

    relative_path: str
    size_bytes: int
    modified_at: str


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def index_exists() -> bool:
    """True only if a *complete* index is present: both files, and an ``index_meta`` row."""
    if not database_path().exists() or not embeddings_path().exists():
        return False
    try:
        with _connect(database_path()) as connection:
            row = connection.execute("SELECT COUNT(*) FROM index_meta").fetchone()
            return bool(row[0])
    except sqlite3.Error:
        return False


def load_meta() -> IndexMeta | None:
    if not index_exists():
        return None
    with _connect(database_path()) as connection:
        row = connection.execute("SELECT * FROM index_meta WHERE id = 1").fetchone()
    if row is None:
        return None
    return IndexMeta(
        folder_path=row["folder_path"],
        built_at=row["built_at"],
        embedding_model=row["embedding_model"],
        chunk_count=row["chunk_count"],
        documents_found=row["documents_found"],
        documents_indexed=row["documents_indexed"],
        documents_skipped=row["documents_skipped"],
    )


def load_matrix() -> np.ndarray:
    """Load the embedding matrix into memory.

    At the stated scale this is tens of megabytes (research.md §2). If the corpus grows by
    an order of magnitude, this is the first decision to revisit.
    """
    return np.load(embeddings_path())


def load_chunks_by_rows(rows: list[int]) -> dict[int, ChunkRecord]:
    """Fetch chunk and document detail for specific embedding rows.

    Only the ranked handful is fetched, not the whole table.
    """
    if not rows:
        return {}
    placeholders = ",".join("?" * len(rows))
    query = f"""
        SELECT c.embedding_row, c.text, c.char_start, c.char_end,
               d.name, d.relative_path, d.path
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.embedding_row IN ({placeholders})
    """
    with _connect(database_path()) as connection:
        found = connection.execute(query, rows).fetchall()
    return {
        row["embedding_row"]: ChunkRecord(
            text=row["text"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            document_name=row["name"],
            document_relative_path=row["relative_path"],
            document_path=row["path"],
        )
        for row in found
    }


def load_fingerprints() -> list[DocumentFingerprint]:
    """Every indexed document's comparison keys, for reconciliation (FR-035)."""
    if not index_exists():
        return []
    with _connect(database_path()) as connection:
        rows = connection.execute(
            "SELECT relative_path, size_bytes, modified_at FROM documents"
        ).fetchall()
    return [
        DocumentFingerprint(
            relative_path=row["relative_path"],
            size_bytes=row["size_bytes"],
            modified_at=row["modified_at"],
        )
        for row in rows
    ]


def load_skipped() -> list[dict[str, str]]:
    if not index_exists():
        return []
    with _connect(database_path()) as connection:
        rows = connection.execute(
            "SELECT name, relative_path, skip_reason FROM documents WHERE status = 'skipped'"
        ).fetchall()
    return [
        {"name": row["name"], "relative_path": row["relative_path"], "reason": row["skip_reason"]}
        for row in rows
    ]


class IndexBuilder:
    """Accumulates a new index in temporary files, then swaps it in atomically.

    Use as a context manager. If the body raises, or the process dies, the temporary files
    are discarded and the previous index is untouched and still readable.
    """

    def __init__(self, folder_path: str, embedding_model: str) -> None:
        self.folder_path = folder_path
        self.embedding_model = embedding_model
        self._db_temp = database_path().with_suffix(".db.building")
        self._npy_temp = embeddings_path().with_suffix(".npy.building")
        self._vectors: list[np.ndarray] = []
        self._next_row = 0
        self._connection: sqlite3.Connection | None = None
        self.documents_found = 0
        self.documents_indexed = 0
        self.documents_skipped = 0

    def __enter__(self) -> IndexBuilder:
        self._db_temp.unlink(missing_ok=True)
        self._npy_temp.unlink(missing_ok=True)
        self._connection = _connect(self._db_temp)
        self._connection.executescript(SCHEMA)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if exc_type is not None:
            # Failed or interrupted: discard the partial build entirely.
            self._db_temp.unlink(missing_ok=True)
            self._npy_temp.unlink(missing_ok=True)

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("IndexBuilder must be used as a context manager")
        return self._connection

    def add_skipped(
        self, *, path: str, name: str, relative_path: str, file_type: str,
        size_bytes: int, modified_at: str, reason: str,
    ) -> None:
        """Record a document that could not be indexed. ``reason`` must be non-empty (SC-007)."""
        if not reason:
            raise ValueError("A skipped document must carry a reason")
        self._db.execute(
            "INSERT INTO documents (path, name, relative_path, file_type, size_bytes,"
            " modified_at, status, skip_reason) VALUES (?, ?, ?, ?, ?, ?, 'skipped', ?)",
            (path, name, relative_path, file_type, size_bytes, modified_at, reason),
        )
        self.documents_found += 1
        self.documents_skipped += 1

    def add_indexed(
        self, *, path: str, name: str, relative_path: str, file_type: str,
        size_bytes: int, modified_at: str, chunks: list, vectors: np.ndarray,
    ) -> None:
        """Record a document and its chunks. Must have at least one chunk."""
        if len(chunks) == 0:
            raise ValueError(
                "A document with no chunks must be recorded as skipped, never as indexed"
            )
        if vectors.shape[0] != len(chunks):
            raise ValueError("Vector count does not match chunk count")

        cursor = self._db.execute(
            "INSERT INTO documents (path, name, relative_path, file_type, size_bytes,"
            " modified_at, status, skip_reason) VALUES (?, ?, ?, ?, ?, ?, 'indexed', NULL)",
            (path, name, relative_path, file_type, size_bytes, modified_at),
        )
        document_id = cursor.lastrowid

        for ordinal, chunk in enumerate(chunks):
            self._db.execute(
                "INSERT INTO chunks (document_id, ordinal, text, char_start, char_end,"
                " embedding_row) VALUES (?, ?, ?, ?, ?, ?)",
                (document_id, ordinal, chunk.text, chunk.char_start, chunk.char_end,
                 self._next_row),
            )
            self._next_row += 1

        self._vectors.append(vectors.astype(np.float32))
        self.documents_found += 1
        self.documents_indexed += 1

    def commit(self) -> IndexMeta:
        """Finalise and swap in. Called only on a fully successful run."""
        matrix = (
            np.vstack(self._vectors)
            if self._vectors
            else np.zeros((0, 384), dtype=np.float32)
        )

        meta = IndexMeta(
            folder_path=self.folder_path,
            built_at=datetime.now(UTC).isoformat(timespec="seconds"),
            embedding_model=self.embedding_model,
            chunk_count=int(matrix.shape[0]),
            documents_found=self.documents_found,
            documents_indexed=self.documents_indexed,
            documents_skipped=self.documents_skipped,
        )

        if meta.documents_found != meta.documents_indexed + meta.documents_skipped:
            raise ValueError("Document counts do not reconcile; refusing to write the index")

        self._db.execute(
            "INSERT INTO index_meta (id, folder_path, built_at, embedding_model, chunk_count,"
            " documents_found, documents_indexed, documents_skipped)"
            " VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
            (meta.folder_path, meta.built_at, meta.embedding_model, meta.chunk_count,
             meta.documents_found, meta.documents_indexed, meta.documents_skipped),
        )
        self._db.commit()
        self._db.close()
        self._connection = None

        # Write through an open handle: np.save() appends '.npy' to any path that does not
        # already end in it, which would silently put the file somewhere we are not about
        # to rename from.
        with open(self._npy_temp, "wb") as handle:
            np.save(handle, matrix)

        # Swap both files in. The window between the two renames is the only moment the
        # pair can disagree, and it is microseconds of a local filesystem metadata
        # operation.
        self._npy_temp.replace(embeddings_path())
        self._db_temp.replace(database_path())

        return meta


def delete_index() -> None:
    database_path().unlink(missing_ok=True)
    embeddings_path().unlink(missing_ok=True)
