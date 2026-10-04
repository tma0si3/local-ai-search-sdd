# Phase 0 Research: Local Document Search

**Feature**: 001-local-document-search | **Date**: 2026-10-03

This document records the technology decisions behind [plan.md](./plan.md). Every decision is
evaluated against constitution v2.0.0, with Principles I (simplicity), VII (no unnecessary
infrastructure), and III/IV (local-only) doing most of the work.

---

## 1. Embedding generation

**Decision**: `sentence-transformers` with the `all-MiniLM-L6-v2` model, run in-process.

**Rationale**: It must run locally (Principle IV, FR-023) and must remain available when Ollama
is not running (SC-006). `all-MiniLM-L6-v2` produces 384-dimensional vectors, is ~90 MB, runs
acceptably on Apple Silicon CPU, and is the most widely documented starting point for semantic
search — which matters for a stated learning project.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Ollama embeddings (`nomic-embed-text`) | Would make indexing and search fail whenever Ollama is down, directly violating SC-006 and FR-021. This is the single most consequential decision in the plan. |
| `fastembed` (ONNX, no PyTorch) | Materially lighter install, but less familiar and less documented. Worth revisiting if `sentence-transformers`' PyTorch dependency proves painful. |
| Larger model (e.g. `all-mpnet-base-v2`) | ~5x slower for modest quality gain at this scale. Premature for an MVP. |
| TF-IDF / BM25 keyword search | Not semantic. FR-014 requires meaning-based ranking. |

**Consequence**: PyTorch arrives as a transitive dependency and dominates install size. Accepted
as the cost of Ollama independence; recorded in the plan's Complexity Tracking.

---

## 2. Vector storage and search

**Decision**: SQLite for metadata and chunk text; a single NumPy `.npy` matrix for embeddings;
brute-force cosine similarity via one matrix multiplication.

**Rationale**: At ~500 documents the expected corpus is roughly 10,000–25,000 chunks. A
25,000 x 384 float32 matrix is ~38 MB and fits comfortably in memory. One `numpy.dot` against it
takes single-digit milliseconds — far inside the 5-second budget in SC-003, and in practice
faster than an approximate index would be once its own overhead is counted. Normalising vectors
at write time reduces cosine similarity to a dot product.

A vector database here would be infrastructure added for a scale that does not exist, which
Principle VII forbids outright.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Chroma | A whole database and server lifecycle for 25k vectors. Principle VII. |
| FAISS | Approximate indexing solves a problem this project does not have, and adds a heavyweight native dependency. |
| `sqlite-vec` extension | Elegant, but adds an extension-loading step and a second failure mode for no measurable gain at this scale. |
| Pickle the whole index | Opaque, version-fragile, and unsafe to load. SQLite is inspectable with standard tools, which serves Principle VIII. |

**Consequence**: The embedding matrix is loaded into memory at startup. At the stated scale this
is tens of megabytes. Should the corpus grow by an order of magnitude, this decision is the first
to revisit.

---

## 3. Text extraction

**Decision**: `pypdf` for PDF, `python-docx` for DOCX, direct UTF-8 read for TXT and Markdown.
Markdown is indexed as raw text without stripping syntax.

**Rationale**: These are the smallest well-maintained pure-Python libraries for each format.
Treating Markdown as plain text keeps a parser out of the dependency list; its syntax markers are
sparse enough not to meaningfully disturb embeddings.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| `unstructured` | One dependency covering all formats, but very heavy and pulls in a large transitive tree. Principle VII. |
| `PyMuPDF` | Faster and better layout handling, but AGPL-licensed — a poor fit for a learning project. |
| `pdfplumber` | Stronger table extraction, which this feature does not need. |
| OCR via `pytesseract` | Explicitly out of scope per the spec's assumptions; scanned PDFs are reported as skipped. |

**Consequence**: Scanned or image-only PDFs yield no text. The spec already requires these to be
reported as skipped with a reason (FR-010), so the behaviour is specified rather than surprising.

---

## 4. Chunking strategy

**Decision**: Fixed-size character windows of ~1,000 characters with ~150 characters of overlap,
split on paragraph boundaries where one falls nearby.

**Rationale**: Chunks must be small enough to be precise and large enough to stand alone as a
readable result (FR-005, FR-015, and the spec's "enough surrounding context" acceptance
scenario). Roughly 1,000 characters is about 200 tokens — comfortably inside the model's 256-token
window. Overlap prevents a relevant passage being bisected at a boundary. Preferring nearby
paragraph breaks avoids cutting mid-sentence for very little extra code.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Sentence-based chunking | Needs a sentence tokenizer, and single sentences are usually too small to stand alone as results. |
| Semantic chunking by embedding distance | Significantly more complex; requires embedding before chunking. Not justified for an MVP. |
| Whole-document embedding | Would defeat FR-014 — "most relevant passage" is the product. |
| LangChain text splitters | A large framework for an algorithm that is about thirty lines. Principle VII. |

**Consequence**: Chunk size and overlap are the main quality levers. They are kept as named
constants so SC-002 can be tuned against the fixture corpus without restructuring anything.

---

## 5. Web layer

**Decision**: FastAPI + Uvicorn bound to `127.0.0.1`, serving one Jinja2 template plus vanilla
JavaScript. No build step.

**Rationale**: A browser UI is required (FR-025), so a web framework is necessary rather than
incidental. FastAPI supplies request validation and typed handlers, removing hand-written parsing
code. Serving one server-rendered page with plain `fetch` calls avoids Node, bundlers, and a
second language runtime entirely.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Flask | Marginally simpler, but manual request validation. The difference is small either way. |
| Streamlit / Gradio | Fastest path to a UI, but imposes its own execution model and makes the HTTP contract and its testing opaque. Harms Principle VIII more than it helps. |
| React / Vue frontend | A build toolchain and a second runtime for one page. Principles II and VII. |
| Terminal UI only | The spec explicitly requires a browser-based interface. |

**Consequence**: Binding to `127.0.0.1` rather than `0.0.0.0` is a deliberate default supporting
FR-026 — the application is not reachable from the network.

---

## 6. Summarization via Ollama

**Decision**: Call Ollama's HTTP API at `http://localhost:11434` using `httpx`. Check
availability before offering summarization. Send only the retrieved passages and the user's
query.

**Rationale**: FR-019 names Ollama. Its HTTP API is stable and needs no SDK, so `httpx` suffices.
FR-020 limits what may be sent; FR-021 and SC-006 require graceful degradation, so availability
is probed rather than assumed, and failures surface as explained states rather than errors.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| `ollama` Python package | A thin wrapper over HTTP calls the project already makes. Principle VII. |
| Running a model in-process (`llama-cpp-python`) | Native build dependencies and model management inside the app. The spec requires Ollama specifically. |
| Streaming responses | Nicer perceived latency, but adds streaming handling to both server and client. Deferred; a progress indicator satisfies the acceptance scenario. |

**Consequence**: Model selection belongs to the user, per the spec's assumptions. The application
reads a configured model name and reports clearly if that model is absent.

---

## 7. Indexing execution and progress reporting

**Decision**: Index in a background thread within the same process. The UI polls a status
endpoint. Each run builds into a temporary location and atomically replaces the previous index on
success.

**Rationale**: FR-012 requires progress reporting, and FR-009 mandates a full rebuild. The
hazard a full rebuild introduces is losing a working index to a failed or interrupted run — the
edge case the spec now explicitly forbids. Build-then-swap removes that hazard without
transactions or recovery logic. A thread keeps everything in one process, which a task queue
would not.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Celery / RQ | A broker and worker processes for one local operation. Principle VII, emphatically. |
| Synchronous blocking request | Would freeze the UI for minutes and make FR-012 unimplementable. |
| `multiprocessing` | Avoids the GIL, but extraction and embedding are already largely non-Python-bound, and it complicates progress reporting. |
| In-place incremental update | Ruled out by the 2026-10-03 clarification. |

**Consequence**: Only one indexing run may be active at a time. A second request — manual or
automatic — is queued rather than rejected, with at most one run ever pending. This closes the
spec's concurrent-indexing edge case and keeps both trigger paths behaving identically.

---

## 10. Automatic re-indexing on file changes (clarified 2026-10-03)

**Decision**: Watch the configured folder recursively with `watchdog`. Coalesce events over a
quiet period of ~5 seconds, then trigger a full rebuild. At most one run pending at a time. The
user can disable watching.

**Rationale**: FR-030 requires the index to track the folder without manual intervention.
`watchdog` wraps macOS FSEvents, so the operating system does the detection rather than the
application polling the filesystem — which at 500 documents across arbitrary subfolders would be
wasteful and slow.

**The tension this creates**: FR-009 mandates a full rebuild. Pairing that with automatic
detection means one edited file re-processes the entire folder — embedding every chunk again.
For 500 documents that is minutes of CPU, triggered by saving a single file. This is the most
expensive consequence of any decision in the plan, and it is accepted deliberately rather than
overlooked.

Three mitigations keep it tolerable:

1. **Debounce** (FR-031) — a burst of edits produces one run, not one per event.
2. **Single pending run** (FR-032) — changes during a run queue exactly one further run,
   regardless of how many arrive. This is what prevents an endless rebuild loop on a
   continuously changing folder.
3. **Off switch** (FR-033) — the user can fall back to manual indexing.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Polling with `os.walk` on a timer | Scans the whole tree repeatedly; wasteful and slower to notice changes. |
| Incremental re-index of changed files only | The correct answer to this problem, but excluded by the FR-009 clarification. See the recommendation below. |
| `watchfiles` | Rust-backed and faster, but `watchdog` is pure Python and better documented — a better fit for a learning project. |
| No watching, show index age instead | Rejected by the user in clarification. |

**Recommendation for a future amendment**: automatic detection and full rebuild are a poor pair.
Incremental indexing (Question 1, Option B) exists precisely to make change-driven re-indexing
cheap. If the rebuild cost proves annoying in practice, revisiting FR-009 is the fix, and the
`Document` entity already stores `modified_at` and `size_bytes`, which is what change detection
would need.

**Constitutional note**: `watchdog` is a new dependency, which Principle VII requires justifying.
It is justified by FR-030 — a present, stated requirement, not a speculative one — and the
alternative (hand-rolled polling) is both more code and worse behaviour.

---

## 8. Configuration persistence

**Decision**: A small JSON file in a platform-appropriate application data directory
(`~/Library/Application Support/localsearch/` on macOS), holding the configured folder path and
the Ollama model name. The index database and embedding matrix live in the same directory.

**Rationale**: FR-002 requires the folder path to survive restarts; the spec's constraints
require artifacts to be written only to a documented application data directory. JSON is
inspectable and editable by hand, which suits Principle VIII.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Config in SQLite | Couples configuration to an index that is destroyed on every rebuild. |
| Environment variables | Not persistable from a UI; FR-001 requires setting the folder in the application. |
| Writing beside the documents | Pollutes the user's folder with application state. |

---

## Resolved unknowns

No `NEEDS CLARIFICATION` markers remain in the Technical Context.

### 9. Opening the source document (clarified 2026-10-03)

**Decision**: Results carry the document's absolute path. A dedicated endpoint hands the file to
macOS via `open` (or `open -R` to reveal in Finder). No in-application rendering.

**Rationale**: Closes the "now what?" gap after a result is found, at near-zero implementation
cost, because the operating system already handles all four formats. An in-browser viewer would
be the largest single piece of scope in the feature and would need per-format rendering
dependencies, which Principle VII rules out.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Name and snippet only | Leaves the user hunting through Finder by hand, undercutting the point of searching. |
| In-browser viewer with match highlighting | Four formats, four rendering problems, plus heavyweight dependencies. Disproportionate for an MVP. |
| Serving the file over HTTP for browser display | Works only for PDF and plain text; DOCX would still need conversion. |

**Security consequence**: the endpoint accepts a path from the client, so it MUST resolve
symlinks and confirm the result lies within the configured documents folder before handing
anything to the operating system. Without that check, any local process able to reach the port
could open arbitrary files. This is recorded as a hard requirement in
`contracts/http-api.md`.

---

## 11. Detecting changes made while the application is closed (resolved during analysis, 2026-10-03)

**Decision**: On startup, and whenever the configured folder changes, walk the folder and compare
file names, sizes, and modification times against what the index recorded. If they differ, the
index is marked stale. With automatic re-indexing enabled, a run starts; with it disabled, the UI
says the index is out of date and offers to re-index. Document contents are never re-read during
this comparison.

**Rationale**: `watchdog` only reports events that occur while the observer is running. A user who
enables automatic re-indexing, quits the application, edits documents, and reopens it would
otherwise get stale results from a UI reporting that watching is active — a silent correctness
failure, and the worst kind, because the interface actively asserts the opposite. The comparison
is metadata-only, so it costs a directory walk (milliseconds at this scale) rather than a rebuild.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Unconditional rebuild at every launch | Correct, but under full-rebuild semantics it means minutes of CPU on every start, including the overwhelmingly common case where nothing changed. |
| Display index age and leave it to the user | Passive, and inconsistent with having chosen automatic re-indexing in the first place. |
| Content hashing instead of metadata | Strictly more accurate, but requires reading every file — approaching the cost of the rebuild it is trying to avoid. |

**Known limitation**: a change that preserves both size and modification time is not detected.
This is rare in practice and the manual re-index path remains available. Worth noting rather than
engineering around.

**Note for review**: this resolution was chosen during `/speckit.analyze` remediation rather
than in a clarification round. It is the one design decision in this feature not directly
traceable to a user answer.

---

## 12. Relevance floor for search results (discovered during implementation, 2026-10-03)

**Decision**: Passages scoring below a cosine similarity of `0.10` are not returned at all.

**Rationale**: FR-016 requires the system to indicate clearly when a query produces no relevant
results — but brute-force ranking over the whole corpus *always* produces a top ten. Without a
floor that state is unreachable, and a question about something the user has never written about
returns ten unrelated passages presented as matches. The empty-results branch in the UI would be
dead code.

This was not visible from the design; it surfaced only when an unrelated query was run against a
real index and returned four passages, the best scoring `-0.034`.

**Choosing the value** — measured against the fixture corpus with `all-MiniLM-L6-v2`:

| Case | Score |
|---|---|
| Direct answer to a question | 0.30 – 0.55 |
| A single relevant sentence buried in a long, repetitive document | ~0.19 |
| Unrelated query | ~0.03, sometimes negative |

A first attempt at `0.15` looked sound against ordinary documents but suppressed the
buried-sentence case completely. That case matters more than the others: finding one sentence
inside a very long document is precisely the search a user cannot perform by hand. `0.10` sits
below it and still an order of magnitude above the noise.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| No floor; show scores and let the user judge | Asks the user to distinguish 0.03 from 0.35 with no reference point. The application knows the difference and should say so. |
| Relative floor (a fraction of the best score) | On a corpus with no good answer at all, the best score is itself noise, so a relative floor would still return it. |
| Return results but label low-confidence ones | More UI for a worse outcome; the honest answer to "nothing here matches" is to say so. |

**Known limitation**: the threshold is a fixed constant tuned on a four-document fixture corpus.
It is exported as `MIN_RELEVANCE_SCORE` and asserted from both directions in
`tests/integration/test_search_quality.py` — one test proves irrelevant queries return nothing,
another proves the diluted needle survives. If retrieval quality is ever tuned, those two tests
are the guard rails.


