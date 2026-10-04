"""Integration tests for the indexing pipeline (T020).

Uses a stub embedder: these assert bookkeeping, not retrieval quality. Quality has its own
test with the real model.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from localsearch import embed, store
from localsearch.indexer import Indexer, scan_folder


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    def fake(texts):
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        rows = np.ones((len(texts), 384), dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)

    monkeypatch.setattr(embed, "embed_texts", fake)


def run_to_completion(indexer: Indexer, folder) -> dict:
    indexer.request_run(folder)
    indexer._thread.join(timeout=120)
    return indexer.snapshot()


def test_scan_finds_documents_at_any_depth(corpus):
    # FR-003: recursive. The kickoff document is two levels down.
    names = {f.name for f in scan_folder(corpus)}
    assert "kickoff-meeting.docx" in names


def test_scan_records_relative_paths(corpus):
    by_name = {f.name: f for f in scan_folder(corpus)}
    assert by_name["kickoff-meeting.docx"].relative_path == "nested/deeper/kickoff-meeting.docx"


def test_scan_ignores_unsupported_types(corpus):
    assert not any(f.name == "notes.pages" for f in scan_folder(corpus))


def test_scan_ignores_hidden_files(corpus, tmp_path):
    folder = tmp_path / "docs"
    shutil.copytree(corpus, folder)
    (folder / ".hidden.txt").write_text("should not be indexed", encoding="utf-8")
    assert not any(f.name == ".hidden.txt" for f in scan_folder(folder))


def test_counts_reconcile(fresh_indexer, corpus):
    status = run_to_completion(fresh_indexer, corpus)
    assert status["state"] == "completed"
    assert status["documents_found"] == status["documents_indexed"] + status["documents_skipped"]


def test_every_skipped_document_carries_a_reason(fresh_indexer, corpus):
    # SC-007: no document is silently dropped.
    run_to_completion(fresh_indexer, corpus)
    skipped = store.load_skipped()
    assert skipped
    for document in skipped:
        assert document["reason"].strip()


def test_the_three_edge_case_files_are_all_skipped(fresh_indexer, corpus):
    run_to_completion(fresh_indexer, corpus)
    names = {d["name"] for d in store.load_skipped()}
    assert {"empty.txt", "whitespace-only.txt"} <= names


def test_unsupported_files_are_not_counted_at_all(fresh_indexer, corpus):
    # .pages is not a document we claim to handle, so it is not "found" and not "skipped".
    status = run_to_completion(fresh_indexer, corpus)
    names = {d["name"] for d in store.load_skipped()}
    assert "notes.pages" not in names
    assert status["documents_found"] == len(scan_folder(corpus))


def test_no_indexed_document_has_zero_chunks(fresh_indexer, corpus):
    run_to_completion(fresh_indexer, corpus)
    matrix = store.load_matrix()
    meta = store.load_meta()
    assert meta.chunk_count == matrix.shape[0]
    assert meta.chunk_count > 0


def test_nested_documents_are_indexed_not_merely_found(fresh_indexer, corpus):
    run_to_completion(fresh_indexer, corpus)
    skipped = {d["relative_path"] for d in store.load_skipped()}
    assert "nested/deeper/kickoff-meeting.docx" not in skipped


def test_one_unreadable_file_does_not_end_the_run(fresh_indexer, corpus, tmp_path):
    # FR-011: a single bad document must not cost the user all the others.
    folder = tmp_path / "docs"
    shutil.copytree(corpus, folder)
    broken = folder / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")

    status = run_to_completion(fresh_indexer, folder)
    assert status["state"] == "completed"
    assert status["documents_indexed"] > 0
    assert "broken.pdf" in {d["name"] for d in store.load_skipped()}


def test_empty_folder_completes_rather_than_failing(fresh_indexer, tmp_path):
    folder = tmp_path / "empty-folder"
    folder.mkdir()
    status = run_to_completion(fresh_indexer, folder)
    assert status["state"] == "completed"
    assert status["documents_found"] == 0


def test_progress_reaches_the_total(fresh_indexer, corpus):
    status = run_to_completion(fresh_indexer, corpus)
    assert status["processed"] == status["total"]
