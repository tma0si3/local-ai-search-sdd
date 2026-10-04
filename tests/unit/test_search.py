"""Unit tests for cosine ranking (T008).

Hand-built normalised matrices only — no model is loaded here, which keeps these tests
fast and keeps the ranking logic testable in isolation (Principle VI).
"""

from __future__ import annotations

import numpy as np
import pytest

from localsearch.search import rank


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_empty_matrix_returns_no_results():
    assert rank(unit(1, 0, 0), np.zeros((0, 3), dtype=np.float32)) == []


def test_results_are_ordered_by_descending_score():
    matrix = np.vstack([unit(0, 1, 0), unit(1, 0, 0), unit(0.7, 0.7, 0)])
    results = rank(unit(1, 0, 0), matrix, limit=3)
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)


def test_closest_vector_ranks_first():
    matrix = np.vstack([unit(0, 1, 0), unit(1, 0, 0), unit(0, 0, 1)])
    results = rank(unit(1, 0, 0), matrix, limit=3)
    assert results[0][0] == 1
    assert results[0][1] == pytest.approx(1.0, abs=1e-5)


def test_limit_larger_than_corpus_returns_the_whole_corpus():
    matrix = np.vstack([unit(1, 0, 0), unit(0, 1, 0)])
    results = rank(unit(1, 0, 0), matrix, limit=50)
    assert len(results) == 2


def test_limit_truncates():
    matrix = np.vstack([unit(1, 0, 0), unit(0, 1, 0), unit(0, 0, 1)])
    assert len(rank(unit(1, 0, 0), matrix, limit=2)) == 2


def test_non_positive_limit_returns_nothing():
    matrix = np.vstack([unit(1, 0, 0)])
    assert rank(unit(1, 0, 0), matrix, limit=0) == []


def test_dimension_mismatch_is_an_explicit_error():
    # This is the failure a MODEL_MISMATCH guard is meant to catch earlier. If it reaches
    # here, the message must still tell the user to re-index rather than showing a raw
    # shape error.
    matrix = np.vstack([unit(1, 0, 0, 0)])
    with pytest.raises(ValueError, match="re-index"):
        rank(unit(1, 0, 0), matrix)


def test_rows_and_scores_have_plain_python_types():
    # These values are serialised to JSON by the API; numpy scalars would not serialise.
    matrix = np.vstack([unit(1, 0, 0)])
    (row, score), = rank(unit(1, 0, 0), matrix)
    assert isinstance(row, int)
    assert isinstance(score, float)


def test_ties_do_not_crash_and_return_all():
    matrix = np.vstack([unit(1, 0, 0), unit(1, 0, 0), unit(1, 0, 0)])
    results = rank(unit(1, 0, 0), matrix, limit=3)
    assert len(results) == 3
    assert {row for row, _ in results} == {0, 1, 2}
