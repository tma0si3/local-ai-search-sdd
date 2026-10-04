"""Ranking chunk embeddings against a query embedding.

Pure: takes arrays, returns ranked rows. No database, no model, no file access. The whole
of the project's "search" is the dot product below; everything else is plumbing around it.

Vectors are L2-normalised at write time (embed.py), so cosine similarity reduces to a dot
product and we skip the division entirely (research.md §2).
"""

from __future__ import annotations

import numpy as np


def rank(
    query_vector: np.ndarray,
    matrix: np.ndarray,
    limit: int = 10,
) -> list[tuple[int, float]]:
    """Return ``(row_index, score)`` pairs, best first.

    ``matrix`` is the full chunk embedding matrix, shape ``(n_chunks, dim)``. Both inputs
    are assumed unit-length. ``limit`` larger than the corpus returns the whole corpus
    rather than erroring, because asking for ten results from a five-chunk index is a
    normal thing to do.
    """
    if matrix.size == 0 or matrix.shape[0] == 0:
        return []
    if limit <= 0:
        return []

    query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    if query.shape[0] != matrix.shape[1]:
        raise ValueError(
            f"Query vector has {query.shape[0]} dimensions but the index has "
            f"{matrix.shape[1]}. The index was built with a different model; re-index."
        )

    scores = matrix @ query

    k = min(limit, scores.shape[0])
    # argpartition finds the top k without sorting the whole array, then we sort only
    # those k. At 25k chunks the difference is immaterial, but it costs nothing.
    top = np.argpartition(-scores, k - 1)[:k] if k < scores.shape[0] else np.arange(scores.shape[0])
    top = top[np.argsort(-scores[top], kind="stable")]

    return [(int(row), float(scores[row])) for row in top]
