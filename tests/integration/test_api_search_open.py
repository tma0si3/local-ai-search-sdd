"""Contract tests for search and the open/reveal endpoint (T032, T034).

The path-containment tests here are the most important in the suite: without that check,
`POST /api/open` would open any file on the machine at the request of anything able to
reach the local port.
"""

from __future__ import annotations

import time
from unittest.mock import patch


def build_index(client, corpus) -> None:
    client.put("/api/config", json={"folder_path": str(corpus)})
    client.post("/api/index")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if client.get("/api/index/status").json()["state"] != "running":
            return
        time.sleep(0.05)
    raise AssertionError("indexing did not finish")


# --- POST /api/search --------------------------------------------------------


def test_search_without_an_index_explains_what_to_do(client):
    response = client.post("/api/search", json={"query": "anything"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_INDEX"
    assert "index" in response.json()["error"]["message"].lower()


def test_empty_query_is_rejected(client, corpus):
    build_index(client, corpus)
    response = client.post("/api/search", json={"query": "   "})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_QUERY"


def test_search_returns_the_documented_result_shape(client, corpus):
    build_index(client, corpus)
    body = client.post("/api/search", json={"query": "erosion"}).json()
    assert body["results"]
    first = body["results"][0]
    for field in ("rank", "document_name", "document_relative_path",
                  "document_path", "snippet", "score"):
        assert field in first


def test_results_are_ranked_from_one(client, corpus):
    build_index(client, corpus)
    results = client.post("/api/search", json={"query": "erosion"}).json()["results"]
    assert [r["rank"] for r in results] == list(range(1, len(results) + 1))


def test_limit_is_honoured(client, corpus):
    build_index(client, corpus)
    results = client.post("/api/search", json={"query": "notes", "limit": 2}).json()["results"]
    assert len(results) <= 2


def test_limit_is_clamped_rather_than_rejected(client, corpus):
    build_index(client, corpus)
    for limit in (0, -5, 10_000):
        response = client.post("/api/search", json={"query": "notes", "limit": limit})
        assert response.status_code == 200
        assert len(response.json()["results"]) <= 50


def test_relative_path_is_returned_for_nested_documents(client, corpus):
    # FR-015: same-named files in different subfolders must be distinguishable.
    build_index(client, corpus)
    results = client.post("/api/search", json={"query": "meeting", "limit": 50}).json()["results"]
    assert any("/" in r["document_relative_path"] for r in results)


def test_model_mismatch_tells_the_user_to_reindex(client, corpus):
    build_index(client, corpus)
    with patch("localsearch.embed.model_name", return_value="some-other-model"):
        response = client.post("/api/search", json={"query": "erosion"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_MISMATCH"
    assert "re-index" in response.json()["error"]["message"].lower()


def test_snippets_are_non_empty(client, corpus):
    build_index(client, corpus)
    results = client.post("/api/search", json={"query": "erosion"}).json()["results"]
    assert all(r["snippet"].strip() for r in results)


# --- POST /api/open ----------------------------------------------------------


def test_opening_a_real_document_succeeds(client, corpus):
    build_index(client, corpus)
    with patch("subprocess.run") as run:
        response = client.post(
            "/api/open", json={"document_path": str(corpus / "budget-review.txt")}
        )
    assert response.status_code == 204
    assert run.called


def test_reveal_mode_uses_the_reveal_flag(client, corpus):
    build_index(client, corpus)
    with patch("subprocess.run") as run:
        client.post(
            "/api/open",
            json={"document_path": str(corpus / "budget-review.txt"), "mode": "reveal"},
        )
    assert "-R" in run.call_args[0][0]


def test_a_path_outside_the_folder_is_refused(client, corpus):
    # The security boundary. A 204 here would be a serious vulnerability.
    build_index(client, corpus)
    with patch("subprocess.run") as run:
        response = client.post("/api/open", json={"document_path": "/etc/passwd"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PATH_OUT_OF_SCOPE"
    assert not run.called, "nothing may be handed to the OS when containment fails"


def test_a_symlink_escaping_the_folder_is_refused(client, corpus, tmp_path):
    """Symlinks must be resolved *before* the containment check, not after.

    A prefix comparison on the raw string would pass this and then open the target.
    """
    import shutil

    folder = tmp_path / "docs"
    shutil.copytree(corpus, folder)

    secret = tmp_path / "outside-secret.txt"
    secret.write_text("private", encoding="utf-8")
    (folder / "innocent-looking.txt").symlink_to(secret)

    client.put("/api/config", json={"folder_path": str(folder)})

    with patch("subprocess.run") as run:
        response = client.post(
            "/api/open", json={"document_path": str(folder / "innocent-looking.txt")}
        )
    assert response.status_code == 403
    assert not run.called


def test_traversal_with_dot_dot_is_refused(client, corpus):
    build_index(client, corpus)
    with patch("subprocess.run") as run:
        response = client.post(
            "/api/open", json={"document_path": f"{corpus}/../../../../etc/passwd"}
        )
    assert response.status_code == 403
    assert not run.called


def test_a_deleted_document_returns_404_not_403(client, corpus, tmp_path):
    # FR-029: a moved file is a normal condition, and must be distinguishable from a
    # security refusal so the UI can explain it properly.
    import shutil

    folder = tmp_path / "docs"
    shutil.copytree(corpus, folder)
    client.put("/api/config", json={"folder_path": str(folder)})

    response = client.post("/api/open", json={"document_path": str(folder / "gone.txt")})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_a_relative_path_is_rejected(client, corpus):
    build_index(client, corpus)
    response = client.post("/api/open", json={"document_path": "budget-review.txt"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PATH"


def test_a_missing_path_is_rejected(client, corpus):
    build_index(client, corpus)
    assert client.post("/api/open", json={}).status_code == 400
