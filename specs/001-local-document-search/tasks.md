---

description: "Task list for local document search implementation"
---

# Tasks: Local Document Search

**Input**: Design documents from `/specs/001-local-document-search/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/http-api.md

**Tests**: Included and mandatory. Constitution v2.0.0 Principle V requires automated tests for
important backend behavior, and bug fixes must ship a failing-first regression test.

**Organization**: Grouped by user story so each can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3, or FOUND for foundational work

## Path Conventions

Single Python project per plan.md: `src/localsearch/`, `tests/` at repository root.

---

## Phase 1: Setup

**Purpose**: Project skeleton and tooling.

- [x] T001 Create `pyproject.toml` with Python 3.12, a `localsearch` entry point, and dependencies: `fastapi`, `uvicorn`, `jinja2`, `sentence-transformers`, `numpy`, `pypdf`, `python-docx`, `watchdog`, `httpx`, `pytest`
- [x] T002 Create the package tree `src/localsearch/` and `src/localsearch/web/{templates,static}/` with `__init__.py` files
- [x] T003 [P] Create `tests/` tree: `tests/unit/`, `tests/integration/`, `tests/fixtures/corpus/`
- [x] T004 [P] Add `tests/fixtures/corpus/` sample documents — one each of `.pdf`, `.txt`, `.md`, `.docx`, plus an empty `.txt`, an unsupported `.pages`, and a nested subfolder file for recursion testing
- [x] T005 [P] Configure `ruff` for linting and formatting in `pyproject.toml`
- [x] T006 [P] Create `README.md` with clone-to-running instructions per quickstart.md (Principle VIII)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared infrastructure. **No user story work can begin until this phase completes.**

### Tests first

- [x] T007 [P] [FOUND] Unit tests for chunking in `tests/unit/test_chunk.py` — size and overlap bounds, paragraph-boundary preference, offsets contiguous and ordered, empty input, input shorter than one chunk
- [x] T008 [P] [FOUND] Unit tests for cosine ranking in `tests/unit/test_search.py` — hand-built normalised matrix, descending score order, k larger than corpus, empty matrix

### Implementation

- [x] T009 [P] [FOUND] Implement `src/localsearch/config.py` — load/save `config.json` under `~/Library/Application Support/localsearch/`; fields `folder_path`, `ollama_model`, `auto_reindex`; resolve app data paths; create the directory when missing
- [x] T010 [P] [FOUND] Implement `src/localsearch/chunk.py` — pure function, text → chunks of ~1000 chars with ~150 overlap, preferring nearby paragraph boundaries; returns text plus `char_start`/`char_end`. No I/O. Makes T007 pass
- [x] T011 [P] [FOUND] Implement `src/localsearch/search.py` — pure function, query vector plus matrix → ranked `(row, score)` list. No database access. Makes T008 pass
- [x] T012 [FOUND] Implement `src/localsearch/store.py` — SQLite schema for `documents`, `chunks`, `index_meta` per data-model.md; NumPy `.npy` matrix read/write; build-to-temp then atomic swap; `load_index()`, `save_index()`, `index_exists()`
- [x] T013 [FOUND] Implement `src/localsearch/embed.py` — load `all-MiniLM-L6-v2` once, embed a list of texts, L2-normalise on write; raise a typed error with actionable text if model weights are absent rather than fetching mid-operation
- [x] T014 [FOUND] Implement the error model in `src/localsearch/errors.py` — typed exceptions mapping to the contract's error codes (`INVALID_PATH`, `PATH_NOT_FOUND`, `PATH_NOT_READABLE`, `NOT_CONFIGURED`, `EMPTY_QUERY`, `NO_INDEX`, `MODEL_MISMATCH`, `FILE_NOT_FOUND`, `PATH_OUT_OF_SCOPE`, `OLLAMA_UNAVAILABLE`, `MODEL_NOT_FOUND`, `NO_RESULTS`), each carrying a message stating what failed and what to do (FR-027)
- [x] T015 [FOUND] Create the FastAPI app in `src/localsearch/web/app.py` — bind `127.0.0.1:8000`, mount static files and templates, exception handler rendering `{"error": {"code", "message"}}`, `GET /` serving the page
- [x] T016 [P] [FOUND] Create `src/localsearch/web/templates/index.html` shell with config, indexing, search, and summary regions
- [x] T017 [P] [FOUND] Create `src/localsearch/web/static/app.css` and `app.js` scaffolding — plain `fetch`, no build step
- [x] T018 [FOUND] Implement the console entry point so `uv run localsearch` starts Uvicorn and prints the URL

**Checkpoint**: foundation ready — user stories can begin.

---

## Phase 3: User Story 1 — Index a documents folder (Priority: P1) 🎯 MVP

**Goal**: The user configures a folder, indexes it, and sees an accurate report of what was found, indexed, and skipped.

**Independent Test**: Point at the fixture corpus, index, and confirm counts and skip reasons are accurate — with no search capability present.

### Tests first

- [x] T019 [P] [US1] Unit tests for extraction in `tests/unit/test_extract.py` — each of the four formats returns text; empty file, unsupported type, and unreadable file each raise a typed error with a reason
- [x] T020 [P] [US1] Integration test in `tests/integration/test_indexer.py` — index the fixture corpus; assert `documents_found = documents_indexed + documents_skipped`, every skipped document carries a non-empty reason (SC-007), nested subfolder files are included (FR-003), and no `indexed` document has zero chunks
- [x] T021 [P] [US1] Contract tests in `tests/integration/test_api_config.py` — `GET`/`PUT /api/config`, plus `400`/`404`/`403` for invalid, missing, and unreadable paths
- [x] T022 [P] [US1] Contract tests in `tests/integration/test_api_index.py` — `POST /api/index` returns `202`; `400 NOT_CONFIGURED` without a folder; a request made while a run is active returns `202` with `rerun_pending: true` rather than an error; `GET /api/index/status` shape for each state
- [x] T023 [P] [US1] Integration test for atomic replacement in `tests/integration/test_index_atomicity.py` — a run that fails partway leaves the previous complete index intact and readable

### Implementation

- [x] T024 [US1] Implement `src/localsearch/extract.py` — `pypdf`, `python-docx`, and UTF-8 reads for TXT/MD; return text or raise a typed error carrying a human-readable skip reason. Makes T019 pass
- [x] T025 [US1] Implement recursive scanning in `src/localsearch/indexer.py` — walk the folder at any depth, select supported extensions, record `path`, `name`, `relative_path`, `file_type`, `size_bytes`, `modified_at` (FR-003)
- [x] T026 [US1] Implement the indexing pipeline in `src/localsearch/indexer.py` — scan → extract → chunk → embed → store; per-document failures recorded as `skipped` with a reason and the run continues (FR-011); a document yielding no text is `skipped`, never `indexed` with zero chunks
- [x] T027 [US1] Implement in-memory indexing state in `src/localsearch/indexer.py` — `state`, `trigger`, `current_file`, `processed`, `total`, `rerun_pending`, `errors`; single-run guard (FR-012)
- [x] T028 [US1] Run indexing in a background thread and write `index_meta` only on success, so an interrupted run never replaces a working index. Makes T023 pass
- [x] T029 [US1] Implement `GET /api/config` and `PUT /api/config` in `web/app.py` with path validation (exists, absolute, readable). Makes T021 pass
- [x] T030 [US1] Implement `POST /api/index` and `GET /api/index/status` in `web/app.py`. Makes T022 pass
- [x] T031 [US1] Build the configuration and indexing UI in `index.html` and `app.js` — folder input, save, start indexing, progress polling with current file, completion report listing every skipped document and its reason

**Checkpoint**: Story 1 is independently functional — quickstart Scenarios 1, 2, 3, 10, 12.

---

## Phase 4: User Story 2 — Search documents by meaning (Priority: P2)

**Goal**: The user enters a natural-language query and receives ranked passages, each showing its document and location, with the ability to open the source.

**Independent Test**: With an index built, query for content known to live in one document and confirm it appears in the top five with name, relative path, and snippet.

### Tests first

- [x] T032 [P] [US2] Contract tests in `tests/integration/test_api_search.py` — `200` with results; `200` with an empty array distinct from an error (FR-016); `400 EMPTY_QUERY`; `409 NO_INDEX`; `409 MODEL_MISMATCH`; `limit` clamped to `1..50`
- [x] T033 [P] [US2] Integration test for retrieval quality in `tests/integration/test_search_quality.py` — known-answer queries against the fixture corpus return the correct document in the top five (SC-002)
- [x] T034 [P] [US2] Contract tests in `tests/integration/test_api_open.py` — `204` on success; `400 INVALID_PATH`; `404 FILE_NOT_FOUND` for a deleted file; **`403 PATH_OUT_OF_SCOPE` for a path outside the configured folder, including via symlink**

### Implementation

- [x] T035 [US2] Implement query embedding and ranking in `src/localsearch/indexer.py` or a thin `query.py` — embed the query, call `search.py`, join ranked rows back to chunk and document records via `store.py`
- [x] T036 [US2] Enforce the embedding-model guard — reject a query when `index_meta.embedding_model` differs from the loaded model, with a message telling the user to re-index (`MODEL_MISMATCH`)
- [x] T037 [US2] Implement `POST /api/search` in `web/app.py` returning `rank`, `document_name`, `document_relative_path`, `document_path`, `snippet`, `score`. Makes T032 pass
- [x] T038 [US2] Implement path containment checking in `src/localsearch/config.py` or a `paths.py` helper — resolve symlinks, then confirm the target lies within the configured folder. **Security-critical**: without this, `POST /api/open` would open arbitrary files at the request of anything reaching the local port
- [x] T039 [US2] Implement `POST /api/open` in `web/app.py` — `open` and `reveal` modes via the macOS `open` command, gated on T038. Makes T034 pass
- [x] T040 [US2] Build the search UI in `index.html` and `app.js` — query box, ranked results showing name, relative path, and snippet; open and reveal controls; distinct empty-results and no-index states
- [x] T041 [US2] Handle a missing source document in the UI — surface the `404` for one result without disturbing the others (FR-029)

**Checkpoint**: Stories 1 and 2 both work — quickstart Scenarios 4, 4b, 5, 6. This is the complete MVP.

---

## Phase 5: User Story 3 — Summarize search results (Priority: P3)

**Goal**: The user requests a plain-language summary of current results, generated by a local Ollama model, with graceful degradation when Ollama is absent.

**Independent Test**: With results on screen, request a summary and confirm it appears; then stop Ollama and confirm the application stays fully usable.

### Tests first

- [x] T042 [P] [US3] Contract tests in `tests/integration/test_api_summarize.py` — `200` with `summary`, `model`, `source_ranks`; `400 NO_RESULTS`; `503 OLLAMA_UNAVAILABLE`; `503 MODEL_NOT_FOUND`
- [x] T043 [P] [US3] Test that `GET /api/summarize/availability` returns `200` with `available: false` and a reason when Ollama is down — **it must never error** (FR-021)
- [x] T044 [P] [US3] Integration test in `tests/integration/test_degraded_mode.py` — with Ollama unreachable, config, index, and search all succeed (SC-006). **This is the test that protects the decision to keep embeddings independent of Ollama**
- [x] T045 [P] [US3] Test that only the query and supplied passages are sent to the model — assert the outbound request body contains no other document content (FR-020)

### Implementation

- [x] T046 [US3] Implement `src/localsearch/summarize.py` — `httpx` client for `http://localhost:11434`, availability probe, model-presence check, typed errors for unreachable and missing-model cases
- [x] T047 [US3] Build the summarization prompt from the query and supplied passages only. Makes T045 pass
- [x] T048 [US3] Implement `GET /api/summarize/availability` and `POST /api/summarize` in `web/app.py`. Makes T042 and T043 pass
- [x] T049 [US3] Build the summary UI in `index.html` and `app.js` — summarize control, in-progress indicator, summary rendered visually distinct from passages, `source_ranks` shown
- [x] T050 [US3] Disable or explain the summarize control when unavailable, leaving results usable. Makes T044 pass at the UI level

**Checkpoint**: all three stories functional — quickstart Scenarios 7, 8.

---

## Phase 6: Automatic Re-Indexing (FR-030–FR-034) — extends US1

**Goal**: The index keeps itself current as folder contents change.

> **Cost warning**: each triggered run is a full rebuild (FR-009). One saved file re-processes the
> entire folder. The three tasks below are the mitigations — treat them as load-bearing, not
> polish. See research.md §10.

### Tests first

- [x] T051 [P] Unit tests for debounce in `tests/unit/test_debounce.py` — a burst of events within the quiet period yields one trigger; events spaced beyond it yield separate triggers
- [x] T052 [P] Integration test in `tests/integration/test_watcher.py` — a change during an active run sets `rerun_pending` and causes **exactly one** further run regardless of how many changes arrive (FR-032). **This is what prevents an endless rebuild loop**
- [x] T053 [P] Integration test — with `auto_reindex` off, filesystem changes trigger nothing (FR-033)
- [x] T053a [P] Integration test in `tests/integration/test_reconcile.py` — given an index and a folder mutated while no observer was running, metadata comparison reports the index stale without re-reading document contents (FR-035); with `auto_reindex` on a run starts, with it off the user is informed (FR-036)
- [x] T053b [P] Integration test — a manual `POST /api/index` during an active run returns `202` with `rerun_pending: true` and causes exactly one further run, never a `409` (FR-032, contract alignment)

### Implementation

- [x] T054 Implement `src/localsearch/watcher.py` — recursive `watchdog` observer over the configured folder; start and stop with configuration changes
- [x] T055 Implement the quiet-period debounce in `watcher.py` (~5s after the last event). Makes T051 pass
- [x] T056 Implement single-pending-run coalescing — never start while a run is active; queue at most one follow-up, shared by manual and automatic triggers. Makes T052 and T053b pass
- [x] T057 Wire `auto_reindex` through `PUT /api/config` to start and stop the observer. Makes T053 pass
- [x] T057a Implement startup and folder-change reconciliation in `src/localsearch/reconcile.py` — compare names, sizes, and modification times against the index; return a stale/fresh verdict. Pure apart from a directory walk. Makes T053a pass
- [x] T057b Call reconciliation at startup and on `folder_path` change; act per FR-036 and expose `index_stale` on `GET /api/config` and `GET /api/index/status`
- [x] T058 Surface `trigger`, `rerun_pending`, and `index_stale` in `GET /api/index/status`, and show watch state plus index age in the UI (FR-034)

**Checkpoint**: quickstart Scenarios 11b and 11c pass.

---

## Phase 7: Polish & Cross-Cutting

- [x] T059 [P] Add structured logging across indexing, search, and summarization — no document content or query text at default verbosity
- [x] T060 [P] Verify every error message states what failed and what to do (FR-027), auditing all codes from T014
- [x] T061 Performance check — index ~500 documents, confirm the run **completes as a whole** with only per-file errors reported (SC-004), then confirm search returns within 5 seconds (SC-003)
- [x] T062 **Privacy verification** — run a full session under a network monitor; confirm no outbound connection except `localhost:11434` (SC-005, FR-022–FR-024). **This is the product's central claim; it must be verified, not assumed**
- [x] T062a [P] Edge-case tests in `tests/integration/test_edge_cases.py` — duplicate and near-identical documents both appear rather than collapsing; a single very large document indexes and is searchable; a query in a language other than the document's returns no spurious top hit
- [x] T063 [P] Update `README.md` with final run and test instructions (SC-008)
- [x] T064 Run every quickstart.md scenario end to end and record the results. **Include an onboarding observation (SC-001)**: a person who has not seen the project reaches a completed index using only the UI and `README.md`, with no verbal help — record where they hesitate
- [x] T065 Confirm `uv run pytest` passes with no network access and with Ollama stopped; any test needing either is skipped with a stated reason

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories**
- **US1 (Phase 3)**: depends on Foundational
- **US2 (Phase 4)**: depends on Foundational. Needs a real index to demonstrate, so in practice follows US1
- **US3 (Phase 5)**: depends on Foundational; consumes US2 results in the UI
- **Auto-reindex (Phase 6)**: depends on US1 — it triggers the US1 pipeline
- **Polish (Phase 7)**: depends on everything desired being complete

### Within each story

- Tests written first and observed to fail before implementation (Principle V)
- Pure modules before the modules that call them
- Services before endpoints; endpoints before UI

### Parallel opportunities

- T003–T006 in Setup
- T007, T008 (tests) then T009, T010, T011 (independent pure modules) in Foundational
- All test tasks within a story — they touch different files
- Once Foundational is done, US1 and the US3 Ollama client (T046) could proceed in parallel with different people

---

## Parallel Example: User Story 1 tests

```bash
# Launch all US1 tests together — different files, no shared state:
Task: "Unit tests for extraction in tests/unit/test_extract.py"
Task: "Integration test for indexing in tests/integration/test_indexer.py"
Task: "Contract tests for config in tests/integration/test_api_config.py"
Task: "Contract tests for indexing in tests/integration/test_api_index.py"
Task: "Atomicity test in tests/integration/test_index_atomicity.py"
```

---

## Implementation Strategy

### MVP first

1. Phase 1 Setup
2. Phase 2 Foundational — blocks everything
3. Phase 3 US1 → **stop and validate** against quickstart Scenarios 1, 2, 3, 10, 12
4. Phase 4 US2 → **stop and validate** against Scenarios 4, 4b, 5, 6

Phases 1–4 are a complete, useful product: index a folder, search it, open what you find.

### Incremental delivery

5. Phase 5 US3 — summarization, plus the degraded-mode guarantee
6. Phase 6 — automatic re-indexing
7. Phase 7 — polish, privacy verification, full quickstart run

### Recommended early checkpoint

After T028 (atomic index write), confirm quickstart Scenario 10 by killing the process mid-run.
Build-then-swap is what makes the full-rebuild decision survivable; verifying it early is cheaper
than discovering a corrupt index later.

---

## Notes

- 71 tasks across 7 phases (T001–T065 plus T053a, T053b, T057a, T057b, T062a — suffixed
  identifiers were added during `/speckit.analyze` remediation so existing numbers stay stable)
- `[P]` means different files and no dependencies
- Verify tests fail before implementing (Principle V)
- Commit after each task or logical group
- Three tasks are disproportionately important: **T038** (path containment — security), **T044**
  (degraded mode — protects the embedding independence decision), **T062** (privacy verification
  — the product's central claim)
