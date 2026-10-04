"""Summarization contract and degraded-mode tests (T042, T043, T044, T045).

The degraded-mode test is the one protecting the project's central architectural choice:
embeddings are computed in-process, not by Ollama, so search survives Ollama being down
(SC-006, research.md §1). If that test ever fails, the design has regressed.

Note on technique: we replace the ``httpx`` reference *inside the summarize module* rather
than patching ``httpx.Client`` globally. The FastAPI test client is itself built on httpx,
so a global patch would cut the wire we are testing over.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from localsearch import summarize


def build_index(client, corpus) -> None:
    client.put("/api/config", json={"folder_path": str(corpus)})
    client.post("/api/index")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if client.get("/api/index/status").json()["state"] != "running":
            return
        time.sleep(0.05)
    raise AssertionError("indexing did not finish")


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _fake_httpx(*, get=None, post=None):
    """A stand-in for the httpx module as summarize.py uses it."""

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def get(self, url, **kwargs):
            if get is None:
                raise httpx.ConnectError("connection refused")
            return get(url, **kwargs)

        def post(self, url, **kwargs):
            if post is None:
                raise httpx.ConnectError("connection refused")
            return post(url, **kwargs)

    return SimpleNamespace(Client=Client, HTTPStatusError=httpx.HTTPStatusError)


@contextmanager
def ollama_down():
    with patch.object(summarize, "httpx", _fake_httpx()):
        yield


@contextmanager
def ollama_with(models: list[str], generate: dict | None = None, capture: dict | None = None):
    def get(url, **kwargs):
        return _FakeResponse({"models": [{"name": name} for name in models]})

    def post(url, **kwargs):
        if capture is not None:
            capture.update(kwargs.get("json") or {})
        return _FakeResponse(generate or {"response": "a summary"})

    with patch.object(summarize, "httpx", _fake_httpx(get=get, post=post)):
        yield


# --- Availability ------------------------------------------------------------


def test_availability_never_errors_when_ollama_is_down(client):
    # FR-021: unavailability is a normal state, not an error.
    with ollama_down():
        response = client.get("/api/summarize/availability")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_unavailability_explains_how_to_fix_it(client):
    with ollama_down():
        body = client.get("/api/summarize/availability").json()
    assert "ollama serve" in body["reason"]
    # And reassures that the rest still works.
    assert "search works" in body["reason"].lower()


def test_a_missing_model_is_reported_distinctly(client):
    with ollama_with(["some-other-model:latest"]):
        body = client.get("/api/summarize/availability").json()
    assert body["available"] is False
    assert "ollama pull" in body["reason"]


def test_a_tagged_model_name_counts_as_installed(client):
    # Ollama reports 'llama3.2:latest'; the configured name is 'llama3.2'.
    with ollama_with(["llama3.2:latest"]):
        assert client.get("/api/summarize/availability").json()["available"] is True


# --- Summarize ---------------------------------------------------------------


def test_summarizing_with_no_results_is_a_clear_error(client):
    response = client.post("/api/summarize", json={"query": "x", "results": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NO_RESULTS"


def test_ollama_unreachable_returns_503(client):
    with ollama_down():
        response = client.post(
            "/api/summarize",
            json={"query": "x", "results": [{"rank": 1, "snippet": "a passage"}]},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "OLLAMA_UNAVAILABLE"


def test_a_missing_model_returns_its_own_code(client):
    with ollama_with(["other-model:latest"]):
        response = client.post(
            "/api/summarize",
            json={"query": "x", "results": [{"rank": 1, "snippet": "a passage"}]},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"


def test_the_503_message_reassures_about_search(client):
    # A user whose summary failed must not think their search results are suspect.
    # The exact wording differs by failure path; what matters is that every path says so.
    with ollama_down():
        body = client.post(
            "/api/summarize",
            json={"query": "x", "results": [{"rank": 1, "snippet": "a passage"}]},
        ).json()
    message = body["error"]["message"].lower()
    assert "search works without it" in message or "unaffected" in message
    assert "ollama serve" in message, "and it must say how to fix it (FR-027)"


def test_a_successful_summary_returns_the_documented_shape(client):
    with ollama_with(["llama3.2:latest"]):
        body = client.post(
            "/api/summarize",
            json={"query": "erosion", "results": [{"rank": 1, "snippet": "Erosion rose."}]},
        ).json()
    assert body["summary"] == "a summary"
    assert body["model"] == "llama3.2"
    assert body["source_ranks"] == [1]


# --- FR-020: only the query and passages are sent ----------------------------


def test_the_prompt_contains_the_query_and_passages():
    prompt = summarize.build_prompt(
        "what about erosion",
        [{"rank": 1, "document_name": "field-study.pdf", "snippet": "Erosion accelerated."}],
    )
    assert "what about erosion" in prompt
    assert "Erosion accelerated." in prompt
    assert "field-study.pdf" in prompt


def test_the_prompt_contains_nothing_from_other_documents(corpus):
    prompt = summarize.build_prompt("q", [{"rank": 1, "snippet": "only this passage"}])
    other = (corpus / "budget-review.txt").read_text(encoding="utf-8")
    assert other.strip() not in prompt


def test_the_outbound_body_carries_only_model_prompt_and_stream(client, corpus):
    """FR-020, asserted on the wire rather than inferred from the prompt builder."""
    captured: dict = {}
    build_index(client, corpus)
    results = client.post("/api/search", json={"query": "erosion", "limit": 1}).json()["results"]

    with ollama_with(["llama3.2:latest"], capture=captured):
        client.post("/api/summarize", json={"query": "erosion", "results": results})

    assert set(captured) == {"model", "prompt", "stream"}

    # No text may appear from any document that was *not* among the supplied results.
    # Which documents those are is decided by the ranking, so derive it rather than
    # assuming — with a stub embedder the ranking is arbitrary.
    returned = {r["document_name"] for r in results}
    for candidate in ("budget-review.txt", "sourdough-notes.md"):
        if candidate in returned:
            continue
        body = (corpus / candidate).read_text(encoding="utf-8").strip()
        first_paragraph = body.split("\n\n")[1] if "\n\n" in body else body
        assert first_paragraph not in captured["prompt"], (
            f"content from {candidate} reached the model, but it was not in the results"
        )


# --- Degraded mode (SC-006) --------------------------------------------------


@pytest.mark.parametrize("step", ["config", "index", "search"])
def test_everything_except_summarizing_works_without_ollama(client, corpus, step):
    """The load-bearing test. If embeddings ever moved to Ollama, this would fail."""
    with ollama_down():
        if step == "config":
            assert client.put(
                "/api/config", json={"folder_path": str(corpus)}
            ).status_code == 200
        elif step == "index":
            build_index(client, corpus)
            assert client.get("/api/index/status").json()["state"] == "completed"
        else:
            build_index(client, corpus)
            response = client.post("/api/search", json={"query": "erosion"})
            assert response.status_code == 200
            assert response.json()["results"]


def test_the_page_still_loads_without_ollama(client):
    with ollama_down():
        assert client.get("/").status_code == 200
