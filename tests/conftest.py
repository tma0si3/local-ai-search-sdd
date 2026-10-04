"""Shared fixtures.

Every test runs against a temporary application data directory, so the suite never touches
the real `~/Library/Application Support/localsearch/`.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

FIXTURE_CORPUS = Path(__file__).parent / "fixtures" / "corpus"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point the application's storage at a throwaway directory."""
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    monkeypatch.setenv("LOCALSEARCH_DATA_DIR", str(data_dir))
    # Avoid a surprise network fetch mid-test if the model is not cached.
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")
    yield data_dir


@pytest.fixture
def corpus() -> Path:
    if not FIXTURE_CORPUS.exists():
        pytest.skip("fixture corpus has not been generated")
    return FIXTURE_CORPUS


@pytest.fixture
def fresh_indexer():
    """A clean Indexer, since the module-level one carries state between tests."""
    from localsearch.indexer import Indexer

    return Indexer()


@pytest.fixture
def client(monkeypatch):
    """A TestClient with the embedding model stubbed out.

    Real embeddings would make every API test load PyTorch and a 90 MB model. The stub is
    deterministic and keeps these tests about the HTTP contract, which is what they are
    for. Retrieval quality is tested separately with the real model.
    """
    import numpy as np
    from fastapi.testclient import TestClient

    from localsearch import embed

    def fake_embed_texts(texts: list[str]) -> np.ndarray:
        """Deterministic stand-in vectors, deliberately all mutually similar.

        They share a dominant direction so every pair scores well above the relevance
        floor in query.py. Otherwise random vectors would sit near zero cosine and be
        filtered out, and these contract tests would be asserting against empty results
        for the wrong reason. Similar strings still do not get similar vectors, which is
        why retrieval quality is tested separately with the real model.
        """
        shared = np.ones(embed.EMBEDDING_DIMENSIONS, dtype=np.float32)
        vectors = []
        for text in texts:
            rng = np.random.default_rng(abs(hash(text)) % (2**32))
            noise = rng.standard_normal(embed.EMBEDDING_DIMENSIONS).astype(np.float32)
            vector = shared + 0.15 * noise
            vectors.append(vector / np.linalg.norm(vector))
        return (
            np.vstack(vectors)
            if vectors
            else np.zeros((0, embed.EMBEDDING_DIMENSIONS), dtype=np.float32)
        )

    monkeypatch.setattr(embed, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(embed, "embed_query", lambda q: fake_embed_texts([q])[0])

    from localsearch.web import app as app_module

    importlib.reload(app_module)
    monkeypatch.setattr(app_module, "watcher", _NullWatcher())

    with TestClient(app_module.app) as test_client:
        test_client.app_module = app_module
        yield test_client


class _NullWatcher:
    """Stand-in so API tests do not start real filesystem observers."""

    enabled = False
    folder = None

    def start(self, folder):
        self.folder = folder
        self.enabled = True

    def stop(self):
        self.folder = None
        self.enabled = False

    @property
    def pending_change(self):
        return False


def ollama_running() -> bool:
    import httpx

    try:
        httpx.get("http://localhost:11434/api/tags", timeout=1.0).raise_for_status()
        return True
    except Exception:
        return False


def embedding_model_cached() -> bool:
    """True if the model is on disk, so tests needing it can skip rather than download."""
    if os.environ.get("LOCALSEARCH_SKIP_MODEL_TESTS") == "1":
        return False
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if not cache.exists():
        return False
    return any(cache.glob("models--sentence-transformers--all-MiniLM-L6-v2"))
