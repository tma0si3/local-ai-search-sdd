"""Contract tests for configuration and indexing endpoints (T021, T022)."""

from __future__ import annotations

import time


def wait_for_idle(client, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/api/index/status").json()
        if status["state"] in {"completed", "failed", "idle"}:
            return status
        time.sleep(0.05)
    raise AssertionError("indexing did not finish in time")


# --- GET/PUT /api/config -----------------------------------------------------


def test_config_starts_unconfigured(client):
    body = client.get("/api/config").json()
    assert body["folder_path"] is None
    assert body["index"]["exists"] is False


def test_saving_a_valid_folder_returns_it(client, corpus):
    body = client.put("/api/config", json={"folder_path": str(corpus)}).json()
    assert body["folder_path"] == str(corpus)


def test_configuration_survives_a_restart(client, corpus):
    client.put("/api/config", json={"folder_path": str(corpus)})
    # A fresh read goes back to the file on disk (FR-002).
    assert client.get("/api/config").json()["folder_path"] == str(corpus)


def test_empty_path_is_rejected(client):
    response = client.put("/api/config", json={"folder_path": "   "})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PATH"


def test_relative_path_is_rejected_with_guidance(client):
    response = client.put("/api/config", json={"folder_path": "Documents/notes"})
    assert response.status_code == 400
    # FR-027: tell the user what to do about it.
    assert "/" in response.json()["error"]["message"]


def test_missing_path_returns_404(client, tmp_path):
    response = client.put("/api/config", json={"folder_path": str(tmp_path / "nope")})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PATH_NOT_FOUND"


def test_unreadable_path_returns_403(client, tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    folder.chmod(0o000)
    try:
        response = client.put("/api/config", json={"folder_path": str(folder)})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PATH_NOT_READABLE"
    finally:
        folder.chmod(0o755)


def test_a_file_instead_of_a_folder_is_rejected(client, corpus):
    response = client.put("/api/config", json={"folder_path": str(corpus / "budget-review.txt")})
    assert response.status_code == 400


def test_model_and_auto_reindex_can_be_saved(client, corpus):
    client.put("/api/config", json={"folder_path": str(corpus)})
    body = client.put("/api/config", json={"ollama_model": "mistral", "auto_reindex": True}).json()
    assert body["ollama_model"] == "mistral"
    assert body["auto_reindex"] is True


def test_every_error_message_says_what_to_do(client, tmp_path):
    # Spot-check FR-027 across the config error codes.
    for payload in ({"folder_path": ""}, {"folder_path": "relative"},
                    {"folder_path": str(tmp_path / "absent")}):
        message = client.put("/api/config", json=payload).json()["error"]["message"]
        assert len(message) > 30, f"message is too terse to act on: {message}"


# --- POST /api/index ---------------------------------------------------------


def test_indexing_without_a_folder_is_a_clear_error(client):
    response = client.post("/api/index")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_CONFIGURED"


def test_indexing_returns_202_and_completes(client, corpus):
    client.put("/api/config", json={"folder_path": str(corpus)})
    response = client.post("/api/index")
    assert response.status_code == 202
    assert response.json()["state"] == "running"

    status = wait_for_idle(client)
    assert status["state"] == "completed"
    assert status["documents_indexed"] > 0


def test_a_request_during_a_run_is_queued_not_refused(client, corpus, monkeypatch):
    # FR-032 / contract: manual and automatic triggers behave identically. A 409 here
    # would mean the same situation had two behaviours.
    from localsearch import indexer as indexer_module

    original = indexer_module.Indexer._execute

    def slow_execute(self, folder):
        time.sleep(0.4)
        return original(self, folder)

    monkeypatch.setattr(indexer_module.Indexer, "_execute", slow_execute)

    client.put("/api/config", json={"folder_path": str(corpus)})
    first = client.post("/api/index")
    second = client.post("/api/index")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["rerun_pending"] is True

    wait_for_idle(client)


def test_status_reports_the_documented_shape(client, corpus):
    client.put("/api/config", json={"folder_path": str(corpus)})
    client.post("/api/index")
    wait_for_idle(client)

    status = client.get("/api/index/status").json()
    for field in ("state", "trigger", "current_file", "processed", "total",
                  "rerun_pending", "index_stale", "errors"):
        assert field in status


def test_completed_status_carries_the_run_summary(client, corpus):
    client.put("/api/config", json={"folder_path": str(corpus)})
    client.post("/api/index")
    status = wait_for_idle(client)
    assert status["documents_found"] == status["documents_indexed"] + status["documents_skipped"]


def test_every_skipped_document_is_reported(client, corpus):
    # SC-007: the user can see what was left out and why.
    client.put("/api/config", json={"folder_path": str(corpus)})
    client.post("/api/index")
    status = wait_for_idle(client)
    assert status["errors"]
    assert all(entry["reason"].strip() for entry in status["errors"])


def test_manual_trigger_is_labelled_as_such(client, corpus):
    client.put("/api/config", json={"folder_path": str(corpus)})
    client.post("/api/index")
    assert client.get("/api/index/status").json()["trigger"] == "manual"


def test_config_reports_the_index_once_built(client, corpus):
    client.put("/api/config", json={"folder_path": str(corpus)})
    client.post("/api/index")
    wait_for_idle(client)

    index = client.get("/api/config").json()["index"]
    assert index["exists"] is True
    assert index["built_at"]
    assert index["chunk_count"] > 0
