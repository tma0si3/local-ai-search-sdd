"""Retrieval quality and corpus edge cases (T033, T062a).

These are the only tests that load the real embedding model, because they are the only
ones whose subject is semantic similarity. Everything else uses a stub, so the suite stays
fast. Skipped rather than failed when the model is not cached — the suite must pass with
no network access.
"""

from __future__ import annotations

import shutil
import time

import pytest

from tests.conftest import embedding_model_cached

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not embedding_model_cached(),
        reason="embedding model is not cached locally; run once with network access",
    ),
]


@pytest.fixture
def real_client(monkeypatch, tmp_path, corpus):
    """A client using genuine embeddings."""
    import importlib

    from fastapi.testclient import TestClient

    from localsearch.web import app as app_module

    importlib.reload(app_module)
    folder = tmp_path / "docs"
    shutil.copytree(corpus, folder)

    with TestClient(app_module.app) as client:
        client.put("/api/config", json={"folder_path": str(folder)})
        client.post("/api/index")
        deadline = time.monotonic() + 300
        while client.get("/api/index/status").json()["state"] == "running":
            assert time.monotonic() < deadline, "indexing timed out"
            time.sleep(0.2)
        client.folder = folder
        yield client


def top_documents(client, query: str, limit: int = 5) -> list[str]:
    results = client.post("/api/search", json={"query": query, "limit": limit}).json()["results"]
    return [r["document_name"] for r in results]


# --- SC-002: known-answer retrieval ------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("how much topsoil was lost from the plots", "field-study-2025.pdf"),
        ("did we spend less than planned this quarter", "budget-review.txt"),
        ("how long should I bake the loaf", "sourdough-notes.md"),
        ("what did the team agree as the first milestone", "kickoff-meeting.docx"),
    ],
)
def test_a_question_finds_the_right_document(real_client, query, expected):
    """The product's whole claim: meaning, not keywords.

    None of these queries share distinctive vocabulary with the passage that answers
    them — 'topsoil' appears in the question and the document, but 'how much ... lost'
    is phrased quite differently from 'Plot B lost an estimated 14 tonnes'.
    """
    assert expected in top_documents(real_client, query)


def test_a_paraphrase_with_no_shared_keywords_still_matches(real_client):
    # 'hedgerow' and 'erosion' are never used in this question.
    assert "field-study-2025.pdf" in top_documents(
        real_client, "which intervention should be prioritised on steep slopes"
    )


def test_scores_descend(real_client):
    results = real_client.post("/api/search", json={"query": "erosion"}).json()["results"]
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


# --- FR-016: no relevant results ---------------------------------------------


def test_a_query_about_nothing_in_the_corpus_returns_no_results(real_client):
    """FR-016 is only reachable because of the relevance floor in query.py.

    Ranking always produces a top ten, so without a floor a question about something the
    user has never written about would return ten unrelated passages presented as
    matches. Showing nothing is more honest than showing noise.
    """
    response = real_client.post(
        "/api/search",
        json={"query": "quantum chromodynamics lattice gauge theory renormalisation"},
    )
    assert response.status_code == 200, "an empty result is not an error"
    assert response.json()["results"] == []


def test_relevant_queries_still_clear_the_floor(real_client):
    # The floor must not be so aggressive that it suppresses genuine answers.
    from localsearch.query import MIN_RELEVANCE_SCORE

    for question in [
        "how much topsoil was lost from the plots",
        "how long should I bake the loaf",
        "what did the team agree as the first milestone",
    ]:
        results = real_client.post("/api/search", json={"query": question}).json()["results"]
        assert results, f"a genuine question returned nothing: {question}"
        assert results[0]["score"] > MIN_RELEVANCE_SCORE


def test_there_is_a_clear_gap_between_relevant_and_irrelevant(real_client):
    """The floor is only defensible if the two populations are actually separated."""
    relevant = real_client.post(
        "/api/search", json={"query": "how much topsoil was lost from the plots"}
    ).json()["results"]
    irrelevant = real_client.post(
        "/api/search", json={"query": "lattice gauge theory renormalisation group flow",
                             "limit": 50},
    ).json()["results"]

    best_irrelevant = max((r["score"] for r in irrelevant), default=0.0)
    assert relevant[0]["score"] > best_irrelevant + 0.2, (
        "relevant and irrelevant scores are too close for a fixed threshold to be sound"
    )


# --- Edge cases (T062a) ------------------------------------------------------


def test_duplicate_documents_both_appear(real_client, tmp_path):
    """Near-identical documents must not silently collapse into one result.

    If they did, a user with a draft and a final version would see only one and might
    conclude the other was not indexed.
    """
    folder = real_client.folder
    shutil.copy(folder / "budget-review.txt", folder / "budget-review-copy.txt")

    real_client.post("/api/index")
    deadline = time.monotonic() + 300
    while real_client.get("/api/index/status").json()["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.2)

    names = top_documents(real_client, "operating expenditure under forecast", limit=10)
    assert "budget-review.txt" in names
    assert "budget-review-copy.txt" in names


def test_a_single_relevant_sentence_in_a_huge_document_is_not_suppressed(real_client):
    """The case that sets the relevance floor.

    A sentence buried in thousands of repetitive paragraphs scores far lower than a
    direct answer — around 0.19 rather than 0.40 — because the chunk containing it is
    mostly filler. This is exactly the search a user cannot do by hand, so the floor must
    stay below it. A floor of 0.15 suppressed this entirely.
    """
    from localsearch.query import MIN_RELEVANCE_SCORE

    folder = real_client.folder
    filler = "This paragraph is about ordinary unremarkable matters.\n\n" * 4000
    needle = "\n\nThe treasure chest was buried beneath the lighthouse steps.\n\n"
    (folder / "large-document.txt").write_text(filler + needle + filler, encoding="utf-8")

    real_client.post("/api/index")
    deadline = time.monotonic() + 600
    while real_client.get("/api/index/status").json()["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.2)

    assert real_client.get("/api/index/status").json()["state"] == "completed"

    results = real_client.post(
        "/api/search", json={"query": "where was the treasure hidden", "limit": 5}
    ).json()["results"]

    assert results, "the buried sentence was suppressed by the relevance floor"
    assert results[0]["document_name"] == "large-document.txt"
    assert "treasure chest" in results[0]["snippet"]
    # Record the headroom, so a future threshold change that breaks this is obvious.
    assert results[0]["score"] > MIN_RELEVANCE_SCORE


def test_a_query_in_another_language_does_not_produce_a_confident_match(real_client):
    """The corpus is English. A Japanese query should not return a spurious top hit.

    This is a limitation worth knowing about rather than a bug: the model is English-only,
    so the honest behaviour is a low score — which the relevance floor then suppresses.
    """
    from localsearch.query import MIN_RELEVANCE_SCORE

    results = real_client.post(
        "/api/search", json={"query": "土壌浸食について教えてください", "limit": 5}
    ).json()["results"]
    # It need not return nothing, but it must not claim a strong match.
    for result in results:
        assert result["score"] >= MIN_RELEVANCE_SCORE
        assert result["score"] < 0.5, (
            "a cross-language query produced a confident match, which would mislead"
        )
