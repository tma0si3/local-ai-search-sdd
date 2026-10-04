# Local Document Search

Semantic search over your own documents, running entirely on your machine. Ask a question in
plain language and get back the passages that answer it — not a list of filenames containing a
keyword.

**Nothing leaves your computer.** The only network connection the application ever makes is to
Ollama on `localhost`, and only when you ask for a summary.

## What it does

- Point it at a folder. It reads PDF, TXT, Markdown, and Word documents, including subfolders.
- Search by meaning. "What did we conclude about soil erosion" finds the right passage even if
  those words never appear together.
- Optionally summarise the results with a local Ollama model.
- Open or reveal the source document in Finder.

## Requirements

- macOS
- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) — **optional**, only for summarisation. Everything else works
  without it.

## Getting started

```sh
uv sync
uv run localsearch
```

Then open <http://127.0.0.1:8000>.

The first run downloads the embedding model (`all-MiniLM-L6-v2`, about 90 MB). That is a one-time
setup cost and the only time the application fetches anything that is not a document of yours.

In the browser:

1. Enter the full path to your documents folder and save it.
2. Click **Start indexing** and watch the progress.
3. Search.

### Optional: summarisation

```sh
ollama serve
ollama pull llama3.2
```

If Ollama is not running, the summarise button is disabled with an explanation. Search keeps
working — that separation is deliberate and is covered by a test.

## Running the tests

```sh
uv run pytest
```

The suite passes with no network access and with Ollama stopped. Tests that need either are
skipped with a stated reason.

## Where your data lives

| Path | Contents |
|---|---|
| `~/Library/Application Support/localsearch/config.json` | Folder path, model name, settings |
| `~/Library/Application Support/localsearch/index.db` | Document and passage text |
| `~/Library/Application Support/localsearch/embeddings.npy` | Passage vectors |

Your documents are only ever read, never modified or copied.

To start over, delete that directory.

## Project layout

```text
src/localsearch/
├── config.py      Settings and application paths
├── errors.py      Typed errors with actionable messages
├── extract.py     PDF / DOCX / TXT / MD → text
├── chunk.py       Text → passages        (pure)
├── search.py      Vectors → ranking      (pure)
├── embed.py       Text → vectors
├── store.py       SQLite + vector matrix (the only module touching the database)
├── indexer.py     Orchestrates a run
├── watcher.py     Notices folder changes
├── reconcile.py   Notices changes made while the app was closed
├── summarize.py   Talks to Ollama
└── web/           FastAPI app, one HTML page, plain JavaScript
```

`chunk.py`, `search.py`, and `extract.py` do no I/O, so they can be tested with plain values.

## Design notes

Full reasoning lives in [`specs/001-local-document-search/`](specs/001-local-document-search/).
Two decisions are worth knowing up front:

- **Embeddings do not come from Ollama.** They are computed in-process, so indexing and search
  keep working when Ollama is down. This costs an extra dependency and is the single most
  consequential choice in the design.
- **Re-indexing rebuilds everything.** Simple and always correct, but a single edited file
  re-processes the whole folder. Automatic re-indexing is debounced and can be switched off.
