# Implementation Plan: Local Document Search

**Branch**: `001-local-document-search` | **Date**: 2026-10-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-local-document-search/spec.md`

## Summary

A single-user, locally run Python application that indexes a folder of PDF, TXT, Markdown, and
DOCX files into a local vector index, answers natural-language queries by semantic similarity,
and optionally summarizes results using a locally running Ollama model.

Technical approach: one Python process serving a minimal browser UI. Text is extracted per
format, split into overlapping chunks, embedded locally with a sentence-transformer model, and
stored in SQLite alongside a NumPy embedding matrix. Search is brute-force cosine similarity over
that matrix — at the stated scale this is faster than any index structure would be, and removes
an entire category of dependency. Summarization calls Ollama over localhost HTTP and is treated
as strictly optional.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**:

- `fastapi` + `uvicorn` — local HTTP server and JSON endpoints
- `jinja2` — one server-rendered HTML page
- `sentence-transformers` — local embedding generation (`all-MiniLM-L6-v2`)
- `numpy` — embedding storage and cosine similarity
- `pypdf` — PDF text extraction
- `python-docx` — DOCX text extraction
- `watchdog` — filesystem change detection for automatic re-indexing
- `httpx` — Ollama HTTP calls
- `pytest` — testing

**Storage**: SQLite (`index.db`) for document and chunk metadata; a NumPy `.npy` file
(`embeddings.npy`) for the embedding matrix. Both under a local application data directory. No
vector database, no ORM, no migrations.

**Testing**: `pytest`. Unit tests for extraction, chunking, and similarity ranking; integration
tests for the index-then-search flow against a small fixture corpus committed to the repo.

**Target Platform**: macOS, local only. The server binds to `127.0.0.1` and is never exposed.

**Project Type**: Single Python project with a server-rendered web UI.

**Performance Goals**: Search results within 5 seconds for 500 documents (SC-003). Brute-force
cosine over an expected ~10,000–25,000 chunks is single-digit milliseconds; the budget is
dominated by embedding the query itself.

**Constraints**:

- No document content, query text, or derived data may leave the machine at runtime (FR-022).
- Configuration, indexing, and search MUST work with Ollama absent (SC-006). This forbids using
  Ollama for embeddings — see Constitution Check below.
- Each index run is a full rebuild (FR-009, clarified 2026-10-03).
- The configured folder is scanned recursively (FR-003, clarified 2026-10-03).
- Folder changes trigger automatic re-indexing after a quiet period (FR-030–FR-034, clarified
  2026-10-03). Because runs are full rebuilds, this is expensive by construction — see
  Complexity Tracking.

**Scale/Scope**: One user, one folder, ~500 documents, four file formats, one HTML page, three
primary flows (configure/index, search, summarize).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against constitution v2.0.0.

| Principle | Status | Evidence |
|---|---|---|
| I. Simple, Understandable Architecture | PASS | One process, one page, a handful of modules. No queues, workers, or services. Data flow is linear: extract → chunk → embed → store → search. |
| II. Python and Open-Source Local Components | PASS | Python 3.12 throughout. Every dependency is OSS and runs locally. No paid or hosted components. |
| III. No Cloud Services Required for the MVP | PASS WITH NOTE | No runtime cloud dependency. One setup-time exception documented below. |
| IV. User Documents Stay on the Local Machine | PASS | Embedding is in-process. Ollama is on localhost. No outbound calls exist in the design. |
| V. Automated Tests for Important Backend Behavior | PASS | Extraction, chunking, and ranking are the non-obvious logic and are unit-tested; the index-then-search path is integration-tested. |
| VI. Small, Independently Testable Components | PASS | Extraction, chunking, embedding, store, and search are separate modules. Core logic takes and returns plain data; filesystem and HTTP live at the edges. |
| VII. No Unnecessary Frameworks or Infrastructure | PASS | Deliberately rejected: vector database, ORM, task queue, frontend build toolchain, Docker. |
| VIII. Easy to Understand and Run Locally | PASS | `uv sync` then one command to run; `pytest` to test. Documented in quickstart.md. |

### Principle III — setup-time network exception

The embedding model weights (~90 MB) and any Ollama model must be downloaded once before first
use. After that, the application runs fully offline, which is what Principle III requires of the
*application*. This is a one-time setup step, equivalent to installing dependencies, not a cloud
service the product depends on.

Mitigation: the model is cached locally after first download; the quickstart documents the step
explicitly; the application does not silently fetch anything at runtime, and reports a clear
error if the model is missing rather than reaching for the network mid-operation.

This is recorded in Complexity Tracking rather than treated as a violation, because no simpler
alternative exists — local embedding requires local weights, which have to arrive somehow.

### Embeddings must not come from Ollama

The obvious simplification — use Ollama for both embedding and summarization, dropping
`sentence-transformers` and its transitive dependencies — is rejected. SC-006 and FR-021 require
indexing and search to work while Ollama is not running. Routing embeddings through Ollama would
make the entire product depend on an optional component. The extra dependency buys that
independence, so it is justified under Principle VII.

## Project Structure

### Documentation (this feature)

```text
specs/001-local-document-search/
├── plan.md              # This file (/speckit-plan command output)
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/
│   └── http-api.md      # Phase 1 output (/speckit-plan command)
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/localsearch/
├── __init__.py
├── config.py            # Load/save the configured folder path and app data paths
├── extract.py           # Per-format text extraction → plain text
├── chunk.py             # Text → overlapping chunks (pure function, no I/O)
├── embed.py             # Text → vectors via the local model
├── store.py             # SQLite + NumPy persistence; load/save/replace index
├── search.py            # Cosine ranking over the embedding matrix (pure function)
├── summarize.py         # Ollama client; availability check and failure handling
├── watcher.py           # Filesystem watching, event debounce, re-index triggering
├── reconcile.py         # Startup/folder-change metadata comparison (FR-035, FR-036)
├── indexer.py           # Orchestrates scan → extract → chunk → embed → store
└── web/
    ├── app.py           # FastAPI routes
    ├── templates/
    │   └── index.html   # The single page
    └── static/
        ├── app.js       # Vanilla JS: fetch, render, no build step
        └── app.css

tests/
├── unit/
│   ├── test_chunk.py
│   ├── test_extract.py
│   ├── test_debounce.py
│   └── test_search.py
├── integration/
│   ├── test_indexer.py
│   └── test_api.py
└── fixtures/
    └── corpus/          # Small committed sample documents, one per format

pyproject.toml
README.md
```

**Structure Decision**: Single Python package under `src/localsearch/`, with the web layer as a
subpackage. There is no separate frontend project — the UI is one Jinja2 template plus vanilla
JavaScript, served by the same process. A split frontend would add a build toolchain and a second
runtime for one page, which Principles II and VII rule out.

Modules are organised so that `chunk.py`, `search.py`, and `extract.py` are pure and I/O-free,
satisfying Principle VI. `indexer.py` is the only module that coordinates several others, and
`store.py` is the only module that touches the database.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Setup-time model download (Principle III) | Local embedding requires local model weights, which must be obtained once | No simpler alternative exists — the only other option is routing embeddings through Ollama, which breaks SC-006 |
| `sentence-transformers` alongside Ollama (Principle VII) | Keeps indexing and search independent of Ollama, as SC-006 requires | Reusing Ollama for embeddings would make the core product fail whenever the optional component is down |
| `watchdog` dependency (Principle VII) | FR-030 requires detecting folder changes; FSEvents via `watchdog` is less code and better behaved than polling | Hand-rolled polling with `os.walk` means repeatedly scanning the whole tree — more code, worse performance, slower detection |
| Full rebuild triggered by single-file changes (Principle I) | The combination of FR-009 (full rebuild) and FR-030 (automatic re-index) is what the user chose in clarification | Incremental indexing would make this cheap, but was explicitly ruled out by the FR-009 clarification. Mitigated by debounce, a single pending run, and an off switch. Flagged in research.md §10 as the first thing to revisit. |
| Separate reconciliation path alongside watching (Principle I) | Filesystem events cannot report changes made while the application was closed, so FR-035 needs a second, metadata-based detection route | Always rebuilding at startup is correct but expensive under full-rebuild semantics; doing nothing leaves the user with stale results while the UI claims to be watching. See research.md §11. |

No other deviations. Notably avoided: vector database (NumPy suffices at this scale), ORM
(`sqlite3` is enough), background task queue (indexing runs in-process with progress reported by
polling), containerisation, and any frontend framework.

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1 artifacts were produced.

- **Principle I**: The data model is two tables plus one derived matrix. Still explainable in a
  single sitting. PASS
- **Principle VI**: `data-model.md` confirms `chunk.py` and `search.py` operate on plain values,
  with persistence isolated in `store.py`. PASS
- **Principle VII**: No new dependency was introduced during design. PASS
- **Principle VIII**: `quickstart.md` provides the full clone-to-running path with expected
  outcomes. PASS

No new violations. Complexity Tracking is unchanged.

