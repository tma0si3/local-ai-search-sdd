# HTTP API Contract: Local Document Search

**Feature**: 001-local-document-search | **Date**: 2026-10-03

The application exposes a small JSON API consumed by its own single-page UI. It binds to
`127.0.0.1` only and is never exposed to the network (FR-026, research.md §5).

**Base URL**: `http://127.0.0.1:8000`

**Conventions**

- Request and response bodies are JSON unless stated otherwise.
- Errors return a non-2xx status with `{"error": {"code": "...", "message": "..."}}`.
- `message` MUST state what failed and what the user can do about it (FR-027).
- No endpoint accepts or returns data that leaves the machine (FR-022).

---

## `GET /`

Serves the single HTML page.

**Response**: `200 OK`, `text/html`.

---

## `GET /api/config`

Returns current configuration and whether a usable index exists.

**Response** `200 OK`:

```json
{
  "folder_path": "/Users/alice/Documents/research",
  "ollama_model": "llama3.2",
  "auto_reindex": true,
  "index": {
    "exists": true,
    "built_at": "2026-10-03T09:14:22",
    "documents_indexed": 487,
    "documents_skipped": 13,
    "chunk_count": 11204
  }
}
```

`folder_path` is `null` when not yet configured. `index.exists` is `false` when no complete index
is present, in which case the remaining `index` fields are `null`. `auto_reindex` reports whether
folder watching is active (FR-034).

Satisfies FR-002, FR-010, FR-034.

---

## `PUT /api/config`

Sets the documents folder, and optionally the Ollama model and automatic re-indexing.

**Request**:

```json
{
  "folder_path": "/Users/alice/Documents/research",
  "ollama_model": "llama3.2",
  "auto_reindex": true
}
```

**Responses**

| Status | Condition |
|---|---|
| `200 OK` | Saved. Returns the same shape as `GET /api/config`. |
| `400 Bad Request` | `folder_path` is empty or not absolute. |
| `404 Not Found` | The path does not exist. |
| `403 Forbidden` | The path exists but is not readable. |

Error codes: `INVALID_PATH`, `PATH_NOT_FOUND`, `PATH_NOT_READABLE`.

Configuration is persisted (FR-002). Changing `folder_path` does not invalidate an existing
index; the user must re-index to reflect the new folder.

Satisfies FR-001, FR-002, and Story 1 scenario 3.

---

## `POST /api/index`

Starts an indexing run. Returns immediately; the run proceeds in the background
(research.md §7).

**Request**: empty body.

**Responses**

| Status | Condition |
|---|---|
| `202 Accepted` | Run started. Body: `{"state": "running", "rerun_pending": false}`. |
| `202 Accepted` | A run was already active; this request was queued. Body: `{"state": "running", "rerun_pending": true}`. |
| `400 Bad Request` | No folder configured. Code `NOT_CONFIGURED`. |

A manual request that arrives while a run is active is **queued, not rejected**, using the same
single-pending-run rule as automatic triggers (FR-032): at most one follow-up run is ever
pending, however many requests arrive. Manual and automatic triggers therefore behave
identically, and there is no `ALREADY_RUNNING` error. The UI distinguishes the two outcomes by
reading `rerun_pending` in the response.

Each run rebuilds the index in full (FR-009). The previous index remains readable until the new
one completes and is swapped in atomically — an interrupted run never replaces a working index.

Satisfies FR-003 through FR-009, FR-011, and the concurrent-indexing edge case.

---

## `GET /api/index/status`

Reports progress. Polled by the UI while a run is active.

**Response** `200 OK`:

```json
{
  "state": "running",
  "trigger": "watch",
  "current_file": "annual-report-2025.pdf",
  "processed": 142,
  "total": 500,
  "rerun_pending": false,
  "index_stale": false,
  "errors": [
    { "name": "scan-001.pdf", "reason": "No extractable text found" }
  ]
}
```

`state` is one of `idle`, `running`, `completed`, `failed`.

`trigger` is `manual` or `watch`, so the UI can explain why indexing started on its own.

`rerun_pending` is `true` when files changed during the current run, or when a manual request
arrived mid-run; exactly one further run will follow, however many triggers arrived (FR-032).

`index_stale` is `true` when a metadata comparison (file names, sizes, modification times) has
found the index out of date — typically because documents changed while the application was not
running (FR-035). The field is also present on `GET /api/config`. When it is `true` and
`auto_reindex` is enabled, a run starts automatically; when `auto_reindex` is disabled, the UI
tells the user the index is out of date and offers to re-index (FR-036).

When `completed`, the body additionally carries the run summary:

```json
{
  "state": "completed",
  "documents_found": 500,
  "documents_indexed": 487,
  "documents_skipped": 13,
  "chunk_count": 11204,
  "errors": [ "..." ]
}
```

Every skipped document appears in `errors` with a reason — no document is silently dropped
(FR-010, SC-007).

Satisfies FR-010, FR-011, FR-012.

---

## `POST /api/search`

Runs a semantic search.

**Request**:

```json
{
  "query": "what were the main findings about soil erosion",
  "limit": 10
}
```

`limit` is optional, defaults to `10`, and is clamped to `1..50`.

**Responses**

| Status | Condition |
|---|---|
| `200 OK` | Search ran. May return zero results. |
| `400 Bad Request` | `query` is empty. Code `EMPTY_QUERY`. |
| `409 Conflict` | No index exists. Code `NO_INDEX`. |
| `409 Conflict` | Index built with a different embedding model. Code `MODEL_MISMATCH`. |

**Success body**:

```json
{
  "query": "what were the main findings about soil erosion",
  "results": [
    {
      "rank": 1,
      "document_name": "field-study-2025.pdf",
      "document_relative_path": "fieldwork/2025/field-study-2025.pdf",
      "document_path": "/Users/alice/Documents/research/fieldwork/2025/field-study-2025.pdf",
      "snippet": "Across all three plots, erosion rates...",
      "score": 0.72
    }
  ]
}
```

An empty `results` array is a valid `200` response and MUST be rendered as "no relevant passages
found", distinct from an error (FR-016).

`MODEL_MISMATCH` exists because comparing vectors across embedding models yields meaningless
rankings (data-model.md, Index). The message instructs the user to re-index.

`document_path` is the absolute path recorded at index time. It is supplied so the UI can offer
the open/reveal action (FR-028) and is never sent anywhere but back to this application.
`document_relative_path` is shown alongside the name so that same-named files in different
subfolders can be told apart (FR-015).

Satisfies FR-013 through FR-017.

---

## `POST /api/open`

Opens a result's source document, or reveals it in Finder, using the operating system's default
handling (FR-028).

**Request**:

```json
{
  "document_path": "/Users/alice/Documents/research/field-study-2025.pdf",
  "mode": "open"
}
```

`mode` is `open` (hand the file to its default application) or `reveal` (select it in Finder).
Defaults to `open`.

**Responses**

| Status | Condition |
|---|---|
| `204 No Content` | Handed off to the operating system. |
| `400 Bad Request` | `document_path` is missing or not absolute. Code `INVALID_PATH`. |
| `403 Forbidden` | Path is not within the indexed folder. Code `PATH_OUT_OF_SCOPE`. |
| `404 Not Found` | File no longer exists at that location. Code `FILE_NOT_FOUND`. |

A `404` MUST leave the rest of the results usable (FR-029) — a moved or deleted file is a normal
condition, not a failure of the search.

**Security note**: the supplied path MUST be resolved and confirmed to lie within the configured
documents folder before any handoff. Without that check this endpoint would open arbitrary files
on the machine at the request of anything that can reach the local port. Symlinks MUST be
resolved before the check, not after.

Satisfies FR-028, FR-029.

---

## `GET /api/summarize/availability`

Reports whether summarization can be offered, so the UI can disable the control rather than
failing after the user clicks it.

**Response** `200 OK`:

```json
{ "available": true, "model": "llama3.2" }
```

When unavailable:

```json
{
  "available": false,
  "model": "llama3.2",
  "reason": "Ollama is not running. Start it with `ollama serve`."
}
```

This endpoint MUST NOT error when Ollama is down — unavailability is a normal state (FR-021,
SC-006).

---

## `POST /api/summarize`

Summarizes a set of search results using the local Ollama model.

**Request**:

```json
{
  "query": "what were the main findings about soil erosion",
  "results": [
    { "rank": 1, "document_name": "field-study-2025.pdf", "snippet": "Across all three plots..." }
  ]
}
```

The client sends back the passages it received. Only the query and these passages reach the model
(FR-020) — no other document content is read during summarization.

**Responses**

| Status | Condition |
|---|---|
| `200 OK` | Summary generated. |
| `400 Bad Request` | `results` is empty. Code `NO_RESULTS`. |
| `503 Service Unavailable` | Ollama unreachable. Code `OLLAMA_UNAVAILABLE`. |
| `503 Service Unavailable` | Configured model not present in Ollama. Code `MODEL_NOT_FOUND`. |

**Success body**:

```json
{
  "summary": "The three field studies agree that erosion accelerated...",
  "model": "llama3.2",
  "source_ranks": [1, 2, 3]
}
```

`source_ranks` lets the UI show which results the summary drew on, and keeps the summary visually
separable from the passages themselves (Story 3, scenario 3).

A `503` here MUST leave search results on screen and usable (FR-021, SC-006).

Satisfies FR-018 through FR-021.

---

## Privacy properties

Enforced by construction across the whole contract:

- Every endpoint is served from `127.0.0.1`.
- The only outbound network call the application makes is to `http://localhost:11434` (Ollama).
- No endpoint accepts a remote URL, callback, or webhook.
- No telemetry endpoint exists (FR-024).

This is what SC-005 verifies by monitoring network activity across a full session.
