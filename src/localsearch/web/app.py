"""FastAPI application: nine endpoints and one HTML page.

Bound to 127.0.0.1 only. The sole outbound call the whole application makes is to Ollama
on localhost, and only when the user asks for a summary (contracts/http-api.md, privacy
properties).
"""

from __future__ import annotations

import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import config as config_module
from .. import query as query_module
from .. import reconcile, store, summarize
from ..errors import LocalSearchError, NotConfiguredError
from ..indexer import indexer
from ..paths import resolve_within
from ..watcher import FolderWatcher

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


# --- Watching ----------------------------------------------------------------


def _trigger_watch_reindex() -> None:
    settings = config_module.load_config()
    if settings.folder_path:
        indexer.request_run(Path(settings.folder_path), trigger="watch")


watcher = FolderWatcher(_trigger_watch_reindex)


def _apply_watch_state(settings: config_module.Config) -> None:
    """Start or stop watching to match the saved setting (FR-033)."""
    if settings.auto_reindex and settings.folder_path:
        folder = Path(settings.folder_path)
        if watcher.folder != folder:
            watcher.start(folder)
    else:
        watcher.stop()


# --- Lifespan ----------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Reconcile the index against the folder at startup, then act (FR-035, FR-036).

    Changes made while the application was closed produce no filesystem events, so
    without this the UI would claim to be watching while serving stale results.
    """
    settings = config_module.load_config()
    _apply_watch_state(settings)

    folder = Path(settings.folder_path) if settings.folder_path else None
    if folder is not None and folder.exists() and reconcile.is_index_stale(folder):
        indexer.mark_stale(True)
        if settings.auto_reindex:
            indexer.request_run(folder, trigger="watch")

    yield

    watcher.stop()


app = FastAPI(title="Local Document Search", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


# --- Request models ----------------------------------------------------------


class ConfigPayload(BaseModel):
    folder_path: str | None = None
    ollama_model: str | None = None
    auto_reindex: bool | None = None


class SearchPayload(BaseModel):
    query: str = ""
    limit: int = query_module.DEFAULT_LIMIT


class OpenPayload(BaseModel):
    document_path: str | None = None
    mode: str = "open"


class SummarizePayload(BaseModel):
    query: str = ""
    results: list[dict] = Field(default_factory=list)


# --- Errors ------------------------------------------------------------------


@app.exception_handler(LocalSearchError)
async def handle_known_error(_: Request, exc: LocalSearchError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


# --- Startup -----------------------------------------------------------------


# --- Page --------------------------------------------------------------------


@app.get("/")
def page(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


# --- Configuration -----------------------------------------------------------


def _config_response(settings: config_module.Config) -> dict:
    meta = store.load_meta()
    index_block: dict = {
        "exists": meta is not None,
        "built_at": meta.built_at if meta else None,
        "documents_indexed": meta.documents_indexed if meta else None,
        "documents_skipped": meta.documents_skipped if meta else None,
        "chunk_count": meta.chunk_count if meta else None,
    }
    return {
        "folder_path": settings.folder_path,
        "ollama_model": settings.ollama_model,
        "auto_reindex": settings.auto_reindex,
        "index": index_block,
        "index_stale": indexer.snapshot()["index_stale"],
    }


@app.get("/api/config")
def get_config() -> dict:
    return _config_response(config_module.load_config())


@app.put("/api/config")
def put_config(payload: ConfigPayload) -> dict:
    settings = config_module.load_config()
    previous_folder = settings.folder_path

    if payload.folder_path is not None:
        settings.folder_path = str(config_module.validate_folder(payload.folder_path))
    if payload.ollama_model:
        settings.ollama_model = payload.ollama_model
    if payload.auto_reindex is not None:
        settings.auto_reindex = payload.auto_reindex

    config_module.save_config(settings)
    _apply_watch_state(settings)

    # A new folder means the existing index describes somewhere else, so re-check (FR-035).
    if settings.folder_path and settings.folder_path != previous_folder:
        folder = Path(settings.folder_path)
        stale = reconcile.is_index_stale(folder) or store.load_meta() is not None
        indexer.mark_stale(bool(stale))
        if stale and settings.auto_reindex:
            indexer.request_run(folder, trigger="watch")

    return _config_response(settings)


# --- Indexing ----------------------------------------------------------------


@app.post("/api/index", status_code=202)
def start_index() -> dict:
    settings = config_module.load_config()
    if not settings.folder_path:
        raise NotConfiguredError(
            "No documents folder is configured. Enter a folder path and save it first."
        )
    return indexer.request_run(Path(settings.folder_path), trigger="manual")


@app.get("/api/index/status")
def index_status() -> dict:
    snapshot = indexer.snapshot()
    snapshot["watching"] = watcher.enabled
    return snapshot


# --- Search ------------------------------------------------------------------


@app.post("/api/search")
def post_search(payload: SearchPayload) -> dict:
    results = query_module.run_search(payload.query, payload.limit)
    return {"query": payload.query, "results": [r.as_dict() for r in results]}


@app.post("/api/open", status_code=204)
def post_open(payload: OpenPayload) -> Response:
    settings = config_module.load_config()
    if not settings.folder_path:
        raise NotConfiguredError("No documents folder is configured.")

    # Security-critical: resolves symlinks and confirms containment before any handoff.
    target = resolve_within(payload.document_path, Path(settings.folder_path))

    arguments = ["open", "-R", str(target)] if payload.mode == "reveal" else ["open", str(target)]
    subprocess.run(arguments, check=False)
    return Response(status_code=204)


# --- Summarization -----------------------------------------------------------


@app.get("/api/summarize/availability")
def summarize_availability() -> dict:
    settings = config_module.load_config()
    return summarize.check_availability(settings.ollama_model).as_dict()


@app.post("/api/summarize")
def post_summarize(payload: SummarizePayload) -> dict:
    settings = config_module.load_config()
    return summarize.summarize(payload.query, payload.results, settings.ollama_model)
