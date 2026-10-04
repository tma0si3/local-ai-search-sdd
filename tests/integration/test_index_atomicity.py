"""Index replacement must be atomic (T023).

A full rebuild is only safe if a failed run cannot destroy the working index it was going
to replace. That is the whole justification for build-to-temp-then-swap (research.md §7),
so it gets its own test.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from localsearch import embed, store
from localsearch.indexer import Indexer


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    def fake(texts):
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        rows = np.ones((len(texts), 384), dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)

    monkeypatch.setattr(embed, "embed_texts", fake)


def build_index(folder) -> dict:
    indexer = Indexer()
    indexer.request_run(folder)
    indexer._thread.join(timeout=120)
    return indexer.snapshot()


def test_a_failing_run_leaves_the_previous_index_intact(corpus, tmp_path, monkeypatch):
    folder = tmp_path / "docs"
    shutil.copytree(corpus, folder)

    first = build_index(folder)
    assert first["state"] == "completed"
    original = store.load_meta()
    original_matrix = store.load_matrix()

    # Fail the second run partway through, after some documents have been processed.
    calls = {"n": 0}

    def exploding_embed(texts):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated failure midway through a rebuild")
        rows = np.ones((len(texts), 384), dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)

    monkeypatch.setattr(embed, "embed_texts", exploding_embed)

    second = build_index(folder)
    assert second["state"] == "failed"
    # And the message should reassure rather than alarm.
    assert "unchanged" in second["message"]

    # The previous index is untouched and still usable.
    survivor = store.load_meta()
    assert survivor is not None
    assert survivor.built_at == original.built_at
    assert survivor.chunk_count == original.chunk_count
    assert store.load_matrix().shape == original_matrix.shape


def test_a_failing_first_run_leaves_no_index_at_all(tmp_path, monkeypatch):
    # Not a half-written one that index_exists() would wrongly accept.
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "note.txt").write_text("some content worth indexing", encoding="utf-8")

    monkeypatch.setattr(
        embed, "embed_texts", lambda texts: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert build_index(folder)["state"] == "failed"
    assert store.index_exists() is False


def test_temporary_files_are_cleaned_up_after_a_failure(tmp_path, monkeypatch):
    from localsearch.config import app_data_dir

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "note.txt").write_text("content", encoding="utf-8")

    monkeypatch.setattr(
        embed, "embed_texts", lambda texts: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    build_index(folder)

    leftovers = list(app_data_dir().glob("*.building"))
    assert leftovers == []


def test_index_is_not_complete_until_meta_is_written(tmp_path):
    # An IndexBuilder abandoned before commit() must not look like a usable index.
    with store.IndexBuilder(str(tmp_path), "test-model"):
        pass
    assert store.index_exists() is False


def test_counts_that_do_not_reconcile_are_refused(tmp_path):
    builder = store.IndexBuilder(str(tmp_path), "test-model")
    with builder:
        builder.documents_found = 99  # deliberately inconsistent
        with pytest.raises(ValueError, match="reconcile"):
            builder.commit()


def test_a_document_with_no_chunks_cannot_be_recorded_as_indexed(tmp_path):
    builder = store.IndexBuilder(str(tmp_path), "test-model")
    with builder, pytest.raises(ValueError, match="skipped"):
        builder.add_indexed(
            path="/x/a.txt", name="a.txt", relative_path="a.txt", file_type="txt",
            size_bytes=1, modified_at="2026-10-03T00:00:00+00:00",
            chunks=[], vectors=np.zeros((0, 384), dtype=np.float32),
        )


def test_a_skipped_document_must_carry_a_reason(tmp_path):
    builder = store.IndexBuilder(str(tmp_path), "test-model")
    with builder, pytest.raises(ValueError, match="reason"):
        builder.add_skipped(
            path="/x/a.txt", name="a.txt", relative_path="a.txt", file_type="txt",
            size_bytes=1, modified_at="2026-10-03T00:00:00+00:00", reason="",
        )
