# Data Model: Local Document Search

**Feature**: 001-local-document-search | **Date**: 2026-10-03

Derived from the Key Entities in [spec.md](./spec.md). Persistence decisions follow
[research.md](./research.md) §2.

## Storage layout

All state lives under one application data directory
(`~/Library/Application Support/localsearch/` on macOS):

```text
config.json         # Configured folder path and Ollama model name
index.db            # SQLite: documents, chunks, index metadata
embeddings.npy      # NumPy float32 matrix, one normalised row per chunk
```

`index.db` and `embeddings.npy` are written together and replaced atomically as a pair by each
indexing run (research.md §7). They are meaningless apart: a chunk's `embedding_row` is an index
into the matrix, so a mismatched pair is a corrupt index.

---

## Entities

### Document

A file discovered in the configured folder. Maps to the spec's **Document**.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `path` | text | Absolute path on disk. Unique within an index. |
| `name` | text | File name shown in results (FR-015) |
| `relative_path` | text | Path relative to the configured folder, shown to disambiguate same-named files in different subfolders (FR-015) |
| `file_type` | text | One of `pdf`, `txt`, `md`, `docx` |
| `size_bytes` | integer | As reported at index time |
| `modified_at` | text | ISO 8601 timestamp from the filesystem |
| `status` | text | `indexed` or `skipped` |
| `skip_reason` | text or null | Required when `status = skipped` (FR-010) |

**Validation rules**

- `path` MUST be unique within an index.
- `relative_path` MUST be expressed relative to the configured folder and MUST NOT escape it.
- `file_type` MUST be one of the four supported types (FR-003).
- `status = skipped` MUST carry a non-empty `skip_reason`. No document may be silently dropped
  (SC-007).
- `status = indexed` MUST correspond to at least one Chunk.
- A document yielding no extractable text MUST be recorded as `skipped`, never as `indexed` with
  zero chunks.

**Lifecycle**: Documents exist only within a single index. A rebuild discards and recreates all
rows; there is no update path.

---

### Chunk

A contiguous passage of text from a Document, sized to stand alone as a search result. Maps to
the spec's **Chunk**.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `document_id` | integer | Foreign key → Document |
| `ordinal` | integer | 0-based position within its Document |
| `text` | text | The passage, as displayed in results |
| `char_start` | integer | Offset into the Document's extracted text |
| `char_end` | integer | Exclusive end offset |
| `embedding_row` | integer | Row index into `embeddings.npy` |

**Validation rules**

- `(document_id, ordinal)` MUST be unique.
- `char_start < char_end`.
- `embedding_row` MUST be unique across the whole index and MUST be a valid row in the matrix.
- `text` MUST be non-empty.

**Relationships**: Many Chunks to one Document. Deleting a Document deletes its Chunks.

---

### Embedding

The vector representation of a Chunk. Maps to the spec's **Embedding**. Not a table — stored as
row `embedding_row` of `embeddings.npy`.

| Property | Value |
|---|---|
| Dimensions | 384 (`all-MiniLM-L6-v2`) |
| Type | `float32` |
| Normalisation | L2-normalised at write time, so cosine similarity reduces to a dot product |

**Validation rules**

- The matrix MUST have exactly as many rows as there are Chunks.
- Every row MUST be unit length within floating-point tolerance.

**Rationale for separation**: Storing vectors as SQLite blobs would mean deserialising thousands
of rows per query. A single contiguous matrix allows one matrix multiplication (research.md §2).

---

### Index

The complete local state for a configured folder, plus the outcome of the most recent run. Maps
to the spec's **Index**. One row only.

| Field | Type | Notes |
|---|---|---|
| `folder_path` | text | The folder this index was built from |
| `built_at` | text | ISO 8601 completion timestamp |
| `embedding_model` | text | Model identifier used to build it |
| `chunk_count` | integer | MUST equal the matrix row count |
| `documents_found` | integer | Reported per FR-010 |
| `documents_indexed` | integer | Reported per FR-010 |
| `documents_skipped` | integer | Reported per FR-010 |

**Validation rules**

- `documents_found = documents_indexed + documents_skipped`.
- A query MUST be rejected if `embedding_model` differs from the model currently loaded —
  comparing vectors across models produces meaningless rankings.
- The presence of this row is what makes an index "complete". An interrupted run never writes
  it, which is how the spec's interrupted-indexing edge case is enforced.

---

### Search Result

A Chunk returned for a query, carrying its ranking. **Transient** — computed per query, never
persisted (the spec's assumptions exclude search history).

| Field | Type | Notes |
|---|---|---|
| `document_name` | text | From the Chunk's Document (FR-015) |
| `document_relative_path` | text | Location within the configured folder, for disambiguation (FR-015) |
| `document_path` | text | Absolute path, for the open/reveal action (FR-028) |
| `snippet` | text | The Chunk's text (FR-015) |
| `score` | float | Cosine similarity in `[-1.0, 1.0]`; higher is better |
| `rank` | integer | 1-based position in the result list |

**Validation rules**

- Results MUST be ordered by descending `score`.
- An empty result list MUST be distinguishable from an error state (FR-016).
- `document_path` MUST be resolved and confirmed to lie within the configured folder before being
  acted on (contracts/http-api.md, `POST /api/open`).

---

### Summary

Generated prose describing a set of Search Results. **Transient** — not persisted.

| Field | Type | Notes |
|---|---|---|
| `text` | text | The generated summary |
| `model` | text | The Ollama model that produced it |
| `source_ranks` | list of integer | Which result ranks fed the summary (FR-020) |

**Validation rules**

- MUST derive only from the supplied passages and query. No other document content may be sent
  (FR-020).
- MUST be distinguishable from retrieved passages in the response, so the UI can render it
  separately (Story 3, scenario 3).

---

## Indexing state

Progress reporting (FR-012) needs in-memory state that is never persisted:

| Field | Type | Notes |
|---|---|---|
| `state` | enum | `idle`, `running`, `completed`, `failed` |
| `trigger` | enum | `manual` or `watch` — why this run started (FR-030) |
| `current_file` | text or null | File being processed |
| `processed` | integer | Documents handled so far |
| `total` | integer | Documents discovered |
| `rerun_pending` | boolean | Files changed during this run; one further run will follow (FR-032) |
| `errors` | list | Per-document failures, each with a reason |

Only one run may be `running` at a time (research.md §7). `rerun_pending` is capped at a single
queued run no matter how many change events arrive, which is what prevents an endless rebuild
loop on a continuously changing folder.

### Watch state

Also in memory only, owned by `watcher.py`:

| Field | Type | Notes |
|---|---|---|
| `enabled` | boolean | Whether watching is active (FR-033, FR-034) |
| `last_event_at` | timestamp or null | Used to measure the quiet period (FR-031) |
| `pending_change` | boolean | A change has been seen but the quiet period has not elapsed |
| `index_stale` | boolean | Set by reconciliation when the folder no longer matches the index (FR-035) |

### Reconciliation inputs

`reconcile.py` compares the folder against the index at startup and whenever `folder_path`
changes. Its comparison keys are exactly three stored `Document` columns — `relative_path`,
`size_bytes`, and `modified_at` — plus the set of files present. This is the load-bearing reason
those columns exist; nothing else reads them. Document contents are never re-read during
reconciliation (FR-035).

---

## Entity relationships

```text
Index (1) ──── (N) Document (1) ──── (N) Chunk (1) ──── (1) Embedding row
                                           │
                                           └──> Search Result (transient)
                                                      │
                                                      └──> Summary (transient)
```

## Module ownership

Supporting Principle VI (small, independently testable components):

| Module | Owns |
|---|---|
| `store.py` | All reads and writes of `index.db` and `embeddings.npy`. The only module importing `sqlite3`. |
| `chunk.py` | Producing Chunk values from text. Pure — takes a string, returns chunks, touches nothing. |
| `search.py` | Ranking. Pure — takes a query vector and the matrix, returns scored rows. No database access. |
| `extract.py` | Document text extraction. Takes a path, returns text or raises a typed error. |
| `indexer.py` | Orchestration and indexing state. The only module coordinating the others. |

This split is what makes the ranking logic testable with a hand-built matrix and no filesystem,
and the chunker testable with a plain string.
