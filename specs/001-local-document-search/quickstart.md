# Quickstart: Local Document Search

**Feature**: 001-local-document-search | **Date**: 2026-10-03

How to run the application and validate that the feature works end to end. Scenarios map to the
acceptance criteria in [spec.md](./spec.md).

> This describes the intended state after implementation. The source tree does not exist yet —
> see [plan.md](./plan.md) for the layout and `tasks.md` (produced by `/speckit.tasks`) for the
> build order.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| macOS | The only supported platform for this MVP |
| Python 3.12 | Checked by `pyproject.toml` |
| `uv` | Dependency and environment management |
| Network access, once | To download the embedding model on first run (~90 MB) |
| Ollama | **Optional.** Required only for summarization |

The one-time model download is the setup-time exception recorded in the plan's Constitution
Check. After it completes, the application runs entirely offline.

---

## Setup

```bash
git clone <repo-url>
cd local-ai-search
uv sync
```

Optional, for summarization only:

```bash
# Install Ollama separately, then:
ollama pull llama3.2
ollama serve
```

---

## Run

```bash
uv run localsearch
```

Expected output:

```text
Local Document Search
Open http://127.0.0.1:8000 in your browser
```

The server binds to `127.0.0.1` and is not reachable from the network.

---

## Run the tests

```bash
uv run pytest
```

Expected: all tests pass without network access and without Ollama running. Tests that would need
either are skipped with a stated reason.

Validates **SC-008**.

---

## Validation scenarios

### Scenario 1 — Index a folder (Story 1, P1)

1. Open `http://127.0.0.1:8000`.
2. Enter the path of a folder containing PDF, TXT, Markdown, and DOCX files.
3. Save, then start indexing.

**Expected**: a document count appears, progress advances with the current file name, and on
completion a report shows documents found, indexed, and skipped — each skipped file with a
reason.

Validates FR-001, FR-003–FR-012, SC-007.

---

### Scenario 2 — Index survives restart (Story 1, scenario 2)

1. Complete Scenario 1.
2. Stop the server (`Ctrl-C`) and start it again.
3. Reload the page.

**Expected**: the folder path is still set and the index summary is still shown. No re-index is
required.

Validates FR-002, FR-008.

---

### Scenario 3 — Bad folder path (Story 1, scenario 3)

1. Enter a path that does not exist.

**Expected**: an error naming the path and the reason. Any existing index is untouched.

Validates FR-027 and Story 1 scenario 3.

---

### Scenario 4 — Search by meaning (Story 2, P2)

1. With an index built, enter a natural-language question whose answer you know lives in one
   specific document.
2. Submit.

**Expected**: ranked results, each showing a document name and a readable snippet, with the
correct document appearing in the top five.

Validates FR-013–FR-015, SC-002. Repeat with ten known-answer queries to measure SC-002
properly.

---

### Scenario 4b — Open a result's source document (Story 2, scenarios 6–7)

1. From a result, choose the open action. Then try the reveal action on another result.
2. Move or delete the file behind a third result, then try to open it.

**Expected**: the document opens in its usual macOS application; reveal selects it in Finder; the
missing file produces a clear "could not be found" message while the other results stay usable.

Validates FR-028, FR-029.

---

### Scenario 5 — Search with no results (Story 2, scenario 3)

1. Search for something unrelated to the corpus.

**Expected**: a clear "no relevant passages found" message — not a blank area, not an error.

Validates FR-016.

---

### Scenario 6 — Search before indexing (Story 2, scenario 4)

1. Clear the application data directory, restart, and search without indexing.

**Expected**: a message explaining that indexing is required first.

Validates FR-017.

---

### Scenario 7 — Summarize results (Story 3, P3)

1. With Ollama running and results on screen, request a summary.

**Expected**: a progress indication, then a summary visually distinct from the passages,
identifying which results it drew on.

Validates FR-018–FR-020.

---

### Scenario 8 — Ollama unavailable (Story 3, scenario 2) — **critical**

1. Stop Ollama (`Ctrl-C` on `ollama serve`).
2. Reload the page, then configure, index, and search.
3. Attempt a summary.

**Expected**: configuration, indexing, and search all work normally. The summarize control is
disabled or explains it is unavailable. Search results stay on screen and usable.

Validates FR-021, SC-006. This is the scenario that justifies embeddings being independent of
Ollama (research.md §1) — if it fails, that decision has been undermined.

---

### Scenario 9 — No data leaves the machine — **critical**

1. Start a network monitor (Little Snitch, or `lsof -i -P | grep python`).
2. Run a full session: configure, index, search, summarize.

**Expected**: no outbound connections except to `localhost:11434` (Ollama). No connection to any
external host, before or after the one-time model download.

Validates FR-022–FR-024, SC-005. This is the product's central privacy claim.

---

### Scenario 10 — Interrupted indexing

1. Start indexing a large folder.
2. Stop the server partway (`Ctrl-C`).
3. Restart and reload.

**Expected**: either the previous complete index is still present, or the application states that
no complete index exists. Never a partial index presented as complete.

Validates the interrupted-indexing edge case and the build-then-swap decision (research.md §7).

---

### Scenario 11 — Re-index after changing files

1. Add, modify, and delete files in the configured folder.
2. Re-run indexing.
3. Search for content from a deleted file and from a new one.

**Expected**: new content is found; deleted content is not. The counts reflect the current folder.

Validates FR-009 and the 2026-10-03 full-rebuild clarification.

---

### Scenario 11b — Automatic re-indexing

1. With automatic re-indexing on and an index built, edit a file in the folder and save it.
2. Wait for the quiet period (~5 seconds).
3. Watch the status area.

**Expected**: indexing starts on its own, labelled as watch-triggered. A burst of several saves
produces one run, not one per save. Changes made during a run queue exactly one further run.

4. Turn automatic re-indexing off and edit another file.

**Expected**: no run starts.

Validates FR-030–FR-034.

> Note: because each run is a full rebuild, this re-processes every document in the folder. On a
> 500-document corpus expect minutes of work from a single file save. See research.md §10.

---

### Scenario 11c — Changes made while the application is closed

1. With an index built and automatic re-indexing on, stop the server.
2. Add, modify, and delete files in the configured folder.
3. Start the server again and open the UI.

**Expected**: the application notices the folder no longer matches the index — by comparing names,
sizes, and modification times, not by re-reading documents — and starts a run on its own.

4. Repeat with automatic re-indexing off.

**Expected**: no run starts, but the UI states that the index is out of date and offers to
re-index. It must not silently present stale results while claiming to be watching.

Validates FR-035 and FR-036. See research.md §11.

---

### Scenario 12 — Unsupported and unreadable files

1. Place a `.pages` file, an empty `.txt`, and a scanned image-only PDF in the folder.
2. Re-index.

**Expected**: all three are reported as skipped with distinct reasons. Indexing of the rest
completes normally.

Validates FR-010, FR-011, SC-007.

---

## Performance check

With roughly 500 documents indexed:

```bash
time curl -s -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "soil erosion findings"}' > /dev/null
```

**Expected**: under 5 seconds, dominated by embedding the query rather than by ranking.

Validates SC-003.

---

## Application data

Everything the application writes lives in one place:

```text
~/Library/Application Support/localsearch/
├── config.json
├── index.db
└── embeddings.npy
```

To reset completely, delete that directory. Nothing is ever written into the user's documents
folder.
