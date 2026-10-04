"""Automatic re-indexing and reconciliation (T052, T053, T053a, T053b).

Two different ways the index learns it is out of date:

* **While running** — filesystem events, debounced (FR-030–FR-033).
* **While closed** — metadata comparison at startup, because no events were observed
  (FR-035, FR-036, research.md §11).

The single-pending-run test is the one that matters most: without coalescing, a folder
being actively written to would rebuild forever, since each rebuild takes longer than the
quiet period.
"""

from __future__ import annotations

import shutil
import threading
import time

import numpy as np
import pytest

from localsearch import embed, reconcile, store
from localsearch.indexer import Indexer


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    def fake(texts):
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        rows = np.ones((len(texts), 384), dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)

    monkeypatch.setattr(embed, "embed_texts", fake)


@pytest.fixture
def folder(corpus, tmp_path):
    destination = tmp_path / "docs"
    shutil.copytree(corpus, destination)
    return destination


def run_once(indexer: Indexer, folder) -> dict:
    indexer.request_run(folder)
    indexer._thread.join(timeout=60)
    return indexer.snapshot()


# --- Single pending run (FR-032) ---------------------------------------------


def test_changes_during_a_run_cause_exactly_one_further_run(folder, monkeypatch):
    runs = []
    started = threading.Event()
    original = Indexer._execute

    def counting_execute(self, path):
        runs.append(time.monotonic())
        started.set()
        time.sleep(0.3)
        return original(self, path)

    monkeypatch.setattr(Indexer, "_execute", counting_execute)

    indexer = Indexer()
    indexer.request_run(folder)
    started.wait(timeout=5)

    # Twenty changes arrive mid-run. Exactly one follow-up must result, not twenty.
    for _ in range(20):
        indexer.request_run(folder, trigger="watch")

    indexer._thread.join(timeout=60)
    assert len(runs) == 2, "a burst during a run must collapse into a single follow-up"


def test_rerun_pending_is_reported_while_a_run_is_queued(folder, monkeypatch):
    original = Indexer._execute
    monkeypatch.setattr(
        Indexer, "_execute", lambda self, p: (time.sleep(0.3), original(self, p))[1]
    )

    indexer = Indexer()
    indexer.request_run(folder)
    time.sleep(0.05)
    response = indexer.request_run(folder, trigger="watch")

    assert response["rerun_pending"] is True
    assert indexer.snapshot()["rerun_pending"] is True
    indexer._thread.join(timeout=60)


def test_a_quiet_run_leaves_nothing_pending(folder):
    status = run_once(Indexer(), folder)
    assert status["rerun_pending"] is False


# --- Watching off (FR-033) ---------------------------------------------------


def test_watching_is_off_unless_enabled(client, folder):
    client.put("/api/config", json={"folder_path": str(folder), "auto_reindex": False})
    assert client.get("/api/index/status").json()["watching"] is False


def test_enabling_auto_reindex_starts_watching(client, folder):
    client.put("/api/config", json={"folder_path": str(folder), "auto_reindex": True})
    assert client.get("/api/index/status").json()["watching"] is True


def test_disabling_auto_reindex_stops_watching(client, folder):
    client.put("/api/config", json={"folder_path": str(folder), "auto_reindex": True})
    client.put("/api/config", json={"auto_reindex": False})
    assert client.get("/api/index/status").json()["watching"] is False


# --- Reconciliation (FR-035, FR-036) -----------------------------------------


def test_a_matching_folder_is_not_stale(folder):
    run_once(Indexer(), folder)
    assert reconcile.is_index_stale(folder) is False


def test_an_added_document_makes_the_index_stale(folder):
    run_once(Indexer(), folder)
    (folder / "new-note.txt").write_text("Something new to find.", encoding="utf-8")
    assert reconcile.is_index_stale(folder) is True


def test_a_deleted_document_makes_the_index_stale(folder):
    run_once(Indexer(), folder)
    (folder / "budget-review.txt").unlink()
    assert reconcile.is_index_stale(folder) is True


def test_an_edited_document_makes_the_index_stale(folder):
    run_once(Indexer(), folder)
    time.sleep(1.1)  # ensure the modification time actually changes
    (folder / "budget-review.txt").write_text("Entirely different content.", encoding="utf-8")
    assert reconcile.is_index_stale(folder) is True


def test_a_changed_folder_makes_the_index_stale(folder, tmp_path):
    run_once(Indexer(), folder)
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert reconcile.is_index_stale(other) is True


def test_no_index_is_not_the_same_as_stale(folder):
    # Absent and out-of-date are different states, acted on differently by the UI.
    assert reconcile.is_index_stale(folder) is False


def test_reconciliation_does_not_read_document_contents(folder, monkeypatch):
    """FR-035 says metadata only. Reading contents would approach a rebuild's cost."""
    run_once(Indexer(), folder)

    from localsearch import extract

    def forbidden(path):
        raise AssertionError(f"reconciliation must not read contents, but read {path}")

    monkeypatch.setattr(extract, "extract_text", forbidden)
    reconcile.is_index_stale(folder)


def test_startup_marks_a_stale_index_without_auto_reindex(client, folder):
    """FR-036: with watching off, the user is told rather than surprised by a rebuild."""
    client.put("/api/config", json={"folder_path": str(folder), "auto_reindex": False})
    client.post("/api/index")
    deadline = time.monotonic() + 60
    while client.get("/api/index/status").json()["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.05)

    time.sleep(1.1)
    (folder / "added-while-closed.txt").write_text("New content.", encoding="utf-8")

    # Simulate a restart: run the lifespan again against the same data directory.
    app_module = client.app_module
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as restarted:
        status = restarted.get("/api/index/status").json()
        assert status["index_stale"] is True
        assert status["state"] != "running", "watching is off, so nothing should start"


def test_meta_records_the_folder_it_was_built_from(folder):
    run_once(Indexer(), folder)
    assert store.load_meta().folder_path == str(folder)
