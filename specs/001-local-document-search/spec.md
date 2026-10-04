# Feature Specification: Local Document Search

**Feature Branch**: `001-local-document-search`

**Created**: 2026-10-03

**Status**: Ready for implementation

**Input**: User description: "Build a simple local AI document search application. The user has a folder on their Mac containing documents such as PDF, TXT, Markdown and DOCX files. The application should: allow the user to configure a local documents folder; scan the folder for supported documents; extract text from documents; split documents into manageable text chunks; create vector embeddings for each chunk; store the embeddings and document metadata locally; allow the user to enter a natural-language search query; return the most semantically relevant document chunks; display document name and relevant text snippets; allow the user to request a summary of the search results; use a locally running Ollama model for summarization; never send document contents to a cloud service. The application should have a very simple browser-based UI. This is an MVP intended primarily as a learning project. Keep the user experience and functionality simple. Do not add authentication, multi-user support, cloud deployment, document collaboration, or enterprise features."

## Clarifications

### Session 2026-10-03

- Q: When the user re-runs indexing on a previously indexed folder, should the application
  rebuild the whole index or only process changed files? → A: Full rebuild. Each indexing run
  discards the previous index for that folder and processes every file afresh. Incremental
  indexing is explicitly out of scope for this feature.
- Q: Should the user be able to open or view the original document from a search result? → A:
  Yes, via the operating system. Each result offers an action that opens the source document in
  the application macOS normally uses, or reveals it in Finder. No in-application document
  rendering.
- Q: Should the application support indexing more than one documents folder? → A: No. One
  configured folder at a time. Changing the folder and re-indexing replaces the previous index.
  Subfolder exclusions and multiple roots are both out of scope.
- Q: Should scanning look inside subfolders, or only at files directly in the configured folder?
  → A: Recursive. The scan descends into subfolders at any depth. Because two subfolders may hold
  files with the same name, results must also show each document's location relative to the
  configured folder.
- Q: Should the application detect changes in the folder and keep the index current on its own?
  → A: Yes, automatically. The application watches the configured folder and re-indexes when
  files change, after a quiet period. Combined with the full-rebuild decision above, each
  triggered run re-processes the entire folder — see the note recorded with FR-030.

### Resolved during analysis, 2026-10-03

- Issue: with automatic re-indexing enabled, changes made while the application was closed would
  never be detected, because the watcher only reacts to live events. The user would silently
  receive stale results while the interface reported watching as active. → Resolution: on
  startup, and whenever the folder is reconfigured, the application compares the folder's current
  contents against the index using file names, sizes, and modification times only. This is a
  metadata comparison, not a re-read of document contents, so it is fast even on large folders.
  If a difference is found and automatic re-indexing is on, a re-index starts; if it is off, the
  user is told the index is out of date. Recorded as FR-035 and FR-036.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Index a documents folder (Priority: P1)

A user opens the application in their browser, enters the path to a folder on their Mac that
holds their documents, and starts indexing. The application reports which files it found, which
it is processing, and when the index is ready to search. The user can re-run indexing later
after adding or changing files.

**Why this priority**: Nothing else in the application can function without an index. This story
alone delivers standalone value — the user learns what is in their folder, which files are
readable, and which are not.

**Independent Test**: Point the application at a folder containing a mix of PDF, TXT, Markdown,
and DOCX files, run indexing, and confirm the application reports an accurate count of
discovered, indexed, and skipped files without any search capability being present.

**Acceptance Scenarios**:

1. **Given** a folder containing supported documents, **When** the user supplies the folder path
   and starts indexing, **Then** the application reports the number of documents found and
   indicates progress until completion.
2. **Given** indexing has completed, **When** the user restarts the application, **Then** the
   previously built index is still available without re-indexing.
3. **Given** a folder path that does not exist or cannot be read, **When** the user starts
   indexing, **Then** the application reports which path failed and why, and makes no changes to
   any existing index.
4. **Given** a folder containing unsupported file types, **When** indexing runs, **Then** those
   files are skipped and reported as skipped rather than causing the run to fail.
5. **Given** a previously indexed folder where some files have been added, changed, or deleted,
   **When** the user re-runs indexing, **Then** the index reflects the current contents of the
   folder.

---

### User Story 2 - Search documents by meaning (Priority: P2)

A user types a natural-language question or phrase into a search box and receives a ranked list
of the most relevant passages from their documents. Each result shows which document it came
from and the matching text, so the user can judge relevance and locate the source.

**Why this priority**: This is the core value of the product, but it depends entirely on Story 1.
Delivered together with Story 1, it constitutes a complete and useful MVP.

**Independent Test**: With an index already built, enter a query whose answer is known to exist
in one specific document, and confirm that a passage from that document appears in the results
with its source name and snippet shown.

**Acceptance Scenarios**:

1. **Given** a built index, **When** the user enters a natural-language query, **Then** the
   application returns a ranked list of relevant passages.
2. **Given** a results list, **When** the user views a result, **Then** the document name and the
   matching text snippet are both displayed.
3. **Given** a query that matches nothing meaningful, **When** results are returned, **Then** the
   application clearly indicates that no relevant passages were found rather than showing an
   empty screen.
4. **Given** no index has been built yet, **When** the user attempts a search, **Then** the
   application explains that indexing is required first.
5. **Given** a result passage, **When** the user inspects it, **Then** the passage is shown in
   full as stored, so that it is understandable without opening the source document.
6. **Given** a result, **When** the user chooses to open or reveal its source document, **Then**
   the operating system opens or reveals that document.
7. **Given** a result whose source document has since been moved or deleted, **When** the user
   tries to open it, **Then** the application explains that the file could no longer be found and
   the other results remain usable.

---

### User Story 3 - Summarize search results (Priority: P3)

After reviewing a set of search results, the user requests a plain-language summary. The
application sends only the retrieved passages to a locally running Ollama model and displays the
generated summary alongside the results the summary was drawn from.

**Why this priority**: This is an enhancement over reading results directly. The application is
fully usable without it, and it introduces an external dependency (a running Ollama instance)
that the first two stories do not have.

**Independent Test**: With a results list on screen, request a summary and confirm that a
coherent summary of those specific passages appears, and that the application continues to
function normally when Ollama is not running.

**Acceptance Scenarios**:

1. **Given** a set of search results, **When** the user requests a summary, **Then** a summary of
   those results is displayed.
2. **Given** the local Ollama service is not running or not reachable, **When** the user requests
   a summary, **Then** the application explains that summarization is unavailable and the search
   results remain usable.
3. **Given** a summary has been produced, **When** the user views it, **Then** it is visually
   distinguishable from the retrieved passages themselves.
4. **Given** summarization is in progress, **When** the user is waiting, **Then** the application
   indicates that work is underway.

---

### Edge Cases

- **Empty or password-protected documents**: A file that yields no extractable text, or that
  cannot be opened, is reported as skipped with a reason; indexing continues with the remaining
  files.
- **Very large documents**: A single large document does not prevent the rest of the folder from
  being indexed.
- **Very large folders**: The user is given ongoing progress feedback rather than an
  unexplained wait.
- **Interrupted indexing**: If indexing is stopped partway, the application does not present a
  partial index as if it were complete. Because each run rebuilds the index in full, an
  interrupted run MUST leave the user with either the previous complete index or a clearly
  reported incomplete state — never a silently truncated index.
- **Duplicate or near-identical documents**: Results drawn from near-identical passages are still
  attributed to their correct source documents.
- **Non-text content**: Scanned PDFs containing only images yield no text and are reported as
  skipped rather than silently producing an empty entry.
- **Folder moved or deleted after indexing**: Search still returns indexed passages, but the
  application indicates that source documents can no longer be located.
- **Query in a different language than the documents**: The application returns its best matches
  without failing.
- **Concurrent actions**: Requesting a second indexing run while one is in progress does not
  corrupt the index. The request is queued rather than refused, following the same
  single-pending-run rule as automatic triggers, so manual and automatic requests behave alike.
- **Rapid or sustained file changes**: A burst of edits produces a single re-index after the
  quiet period, not one per change. Changes arriving during a run trigger exactly one further run
  afterwards, however many arrive.
- **Continuously changing folder**: If files change faster than indexing completes, the
  application does not re-index without end — it keeps at most one run pending, and the user can
  turn automatic re-indexing off.
- **Changes while the application is not running**: Modifications made while the application is
  closed produce no filesystem events. They are detected at startup by comparing file names,
  sizes, and modification times against the index, and handled per FR-035 and FR-036.
- **Index built from a different folder**: If the configured folder is changed, the existing
  index is treated as out of date until a run completes for the new folder.

## Requirements *(mandatory)*

### Functional Requirements

> Requirements are grouped by topic. Identifiers reflect the order in which requirements were
> added, not the order in which they are read, so numbering is not sequential within a group.
> Identifiers are never reused or renumbered once assigned.

**Configuration and indexing**

- **FR-001**: Users MUST be able to specify the path of a local folder containing their documents.
- **FR-002**: The configured folder path MUST persist across application restarts.
- **FR-003**: The system MUST scan the configured folder and all of its subfolders, at any depth,
  and identify documents of supported types: PDF, TXT, Markdown, and DOCX.
- **FR-004**: The system MUST extract plain text from each supported document.
- **FR-005**: The system MUST divide extracted text into chunks small enough to be individually
  meaningful as search results.
- **FR-006**: The system MUST generate a vector embedding for each chunk.
- **FR-007**: The system MUST store embeddings, chunk text, and document metadata on the local
  machine.
- **FR-008**: The stored index MUST remain usable across application restarts without
  re-indexing.
- **FR-009**: Users MUST be able to re-run indexing so the index reflects added, changed, or
  removed files. Each run MUST rebuild the index for the configured folder in full, discarding
  the previous index rather than updating it in place.
- **FR-010**: The system MUST report, for each indexing run, how many documents were found,
  indexed, and skipped, and MUST give a reason for each skipped document.
- **FR-011**: The system MUST continue indexing remaining documents when an individual document
  fails to process.
- **FR-012**: The system MUST report indexing progress while a run is underway.
- **FR-030**: The system MUST detect additions, modifications, and deletions within the
  configured folder and its subfolders while the application is running, and MUST re-index
  automatically in response.

  *Note: combined with FR-009, any single detected change causes the whole folder to be
  re-processed. This is a deliberate accepted cost of pairing automatic detection with full
  rebuilds.*

- **FR-031**: The system MUST wait for a quiet period after the last detected change before
  starting an automatic re-index, so that a burst of changes produces one run rather than many.
  The quiet period MUST default to approximately five seconds and MUST be adjustable without
  code changes.
- **FR-032**: The system MUST NOT start an automatic re-index while another run is in progress.
  If changes occur during a run, the system MUST re-index again once that run completes.
- **FR-033**: Users MUST be able to turn automatic re-indexing off and index manually instead.
- **FR-034**: The system MUST show whether automatic re-indexing is active, and MUST show when
  the index was last built.
- **FR-035**: On startup, and whenever the configured folder changes, the system MUST determine
  whether the index is out of date by comparing the folder's current contents against the index
  using file names, sizes, and modification times. This comparison MUST NOT re-read document
  contents.
- **FR-036**: When the index is found to be out of date, the system MUST start a re-index if
  automatic re-indexing is enabled, and MUST otherwise tell the user that the index is out of
  date and how to refresh it.

**Search**

- **FR-013**: Users MUST be able to enter a natural-language query as free text.
- **FR-014**: The system MUST return document chunks ranked by semantic relevance to the query.
- **FR-015**: Each result MUST display the originating document's name and the relevant text
  snippet, together with the document's location relative to the configured folder so that
  same-named files in different subfolders can be told apart.
- **FR-016**: The system MUST indicate clearly when a query produces no relevant results.
- **FR-017**: The system MUST indicate clearly when a search is attempted before any index exists.
- **FR-028**: Users MUST be able to open the source document of a search result, or reveal it in
  the file manager, using the operating system's default handling for that file type.
- **FR-029**: The system MUST report clearly when the source document of a result can no longer
  be found at its indexed location, and MUST keep the remaining results usable.

**Summarization**

- **FR-018**: Users MUST be able to request a summary of the current search results.
- **FR-019**: The system MUST generate summaries using a locally running Ollama model.
- **FR-020**: The system MUST pass only the retrieved result passages and the user's query to the
  summarization model.
- **FR-021**: The system MUST report when summarization is unavailable and MUST keep search
  results usable in that state.

**Privacy**

- **FR-022**: The system MUST NOT transmit document contents, extracted text, chunks, embeddings,
  or queries to any non-local service.
- **FR-023**: All processing — text extraction, embedding, storage, search, and summarization —
  MUST occur on the local machine.
- **FR-024**: The system MUST NOT collect telemetry or usage analytics.

**Interface and scope**

- **FR-025**: The system MUST provide a browser-based interface covering folder configuration,
  indexing, search, and summarization.
- **FR-026**: The system MUST operate as a single-user local application with no authentication,
  no user accounts, and no multi-user separation.
- **FR-027**: Error messages MUST state what failed and what the user can do about it.

### Key Entities

- **Document**: A single file discovered in the configured folder. Attributes include its file
  name, location within the folder, file type, size, last-modified time, and processing status
  (indexed or skipped with a reason).
- **Chunk**: A contiguous passage of text extracted from a Document, sized to stand alone as a
  search result. Attributes include its text content, its position within the source Document,
  and a reference to that Document.
- **Embedding**: The vector representation of a Chunk's meaning, used to rank Chunks against a
  query. Each Embedding belongs to exactly one Chunk.
- **Index**: The complete local collection of Documents, Chunks, and Embeddings for a configured
  folder, together with the state of the most recent indexing run.
- **Search Result**: A Chunk returned in response to a query, carrying its relevance ranking,
  its source Document's name, that Document's location relative to the configured folder, and its
  full location on disk so the Document can be opened or revealed.
- **Summary**: Generated prose describing a set of Search Results, associated with the query and
  the results it was derived from.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can go from opening the application to a completed index of their
  documents folder without consulting documentation beyond the on-screen instructions.
- **SC-002**: For a query whose answer is known to exist in the indexed documents, a passage from
  the correct document appears within the top five results in at least 9 of 10 trial queries.
- **SC-003**: Search results are returned within 5 seconds for a collection of 500 documents.
- **SC-004**: Indexing a collection of 500 typical documents completes without manual
  intervention and without failing as a whole.
- **SC-005**: Across a full session of configuring, indexing, searching, and summarizing, no
  document content, query text, or derived data leaves the local machine. Verifiable by
  monitoring network activity.
- **SC-006**: The application remains usable for configuration, indexing, and search when the
  local Ollama service is not running.
- **SC-007**: Every document that fails to process is accounted for in the indexing report with a
  stated reason; no document is silently dropped.
- **SC-008**: A developer unfamiliar with the project can start the application and its tests
  using only the documented commands.

## Assumptions

These defaults were chosen where the feature description did not specify details. Each can be
revisited during `/speckit.clarify` or planning.

- **Single folder**: Confirmed in clarification. The user configures one documents folder at a
  time; changing it and re-indexing replaces the previous index. Multiple roots and
  per-subfolder exclusions are both out of scope for this feature.
- **Single user, single machine**: The application serves one local user on macOS. No
  authentication, accounts, or multi-user support, per the explicit exclusions.
- **Local-only web UI**: "Browser-based" means a local server the user opens in their browser.
  It is not exposed to the network and is not deployed anywhere.
- **Manual indexing with automatic refresh**: Confirmed in clarification. The user can index on
  demand, and the application also watches the configured folder and re-indexes automatically
  after a quiet period. Automatic re-indexing can be turned off. Changes made while the
  application is not running are picked up at the next run, whether manual or automatic.
- **Full re-index on demand**: Confirmed in clarification. Re-running indexing rebuilds the index
  from scratch. Incremental updating is explicitly out of scope for this feature and may be
  proposed later as its own feature.
- **Ollama is user-managed**: The user installs, runs, and selects their Ollama model. The
  application does not install or manage Ollama, and treats it as an optional dependency.
- **Embeddings are generated locally**: The embedding capability runs on the local machine,
  consistent with the privacy requirements.
- **Text-based documents only**: Documents are assumed to contain extractable text. Optical
  character recognition for scanned images is out of scope.
- **No in-application document viewer**: Confirmed in clarification. Results show the document
  name and snippet, with an action to open or reveal the file through the operating system. The
  application does not render document contents itself, and does not scroll to or highlight the
  matching passage within the original file.
- **No search history**: Queries and results are not retained between sessions.
- **Learning project**: Scale, concurrency, and performance tuning are deliberately secondary to
  clarity and simplicity, consistent with the project constitution.
