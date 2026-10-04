"""Turning text into vectors, locally.

**The load-bearing decision in this project**: embeddings are computed in-process with
`sentence-transformers`, *not* by Ollama. If they came from Ollama, indexing and search
would fail whenever Ollama was not running, which SC-006 forbids (research.md §1).

The cost is a PyTorch dependency and a one-time ~90 MB model download. That trade is
recorded in plan.md's Complexity Tracking.
"""

from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

from .errors import EmbeddingModelUnavailableError

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


@lru_cache(maxsize=1)
def _load_model():
    """Load the model once per process. Costs a few seconds; worth caching."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise EmbeddingModelUnavailableError(
            "The embedding library is not installed. Run 'uv sync' and try again."
        ) from exc

    offline = os.environ.get("LOCALSEARCH_OFFLINE") == "1"
    try:
        return SentenceTransformer(MODEL_NAME, local_files_only=offline)
    except Exception as exc:
        raise EmbeddingModelUnavailableError(
            f"The embedding model '{MODEL_NAME}' is not available locally and could not be "
            "downloaded. Connect to the internet once to complete setup, then try again. "
            "This is the only download the application needs; your documents are never sent "
            "anywhere."
        ) from exc


def model_name() -> str:
    return MODEL_NAME


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed passages, L2-normalised.

    Normalising here means cosine similarity reduces to a dot product at query time, so
    search.py does one matrix multiplication and no division.
    """
    if not texts:
        return np.zeros((0, EMBEDDING_DIMENSIONS), dtype=np.float32)
    vectors = _load_model().encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return np.asarray(vectors, dtype=np.float32)


def embed_query(query: str) -> np.ndarray:
    """Embed a single query. Same model, same normalisation — necessarily so."""
    return embed_texts([query])[0]
