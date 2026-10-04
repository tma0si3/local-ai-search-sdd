"""Summarization via a local Ollama model (FR-018 – FR-021).

Two things this module must get right:

1. **Only the query and the supplied passages are sent** (FR-020). Nothing else is read
   during summarization — not the source documents, not other chunks.
2. **Unavailability is a normal state, not an error** (FR-021, SC-006). Ollama being down
   must leave search fully usable, so availability is probed rather than assumed.

Plain `httpx` against the HTTP API; the `ollama` package would be a wrapper around calls
we already make (research.md §6).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .errors import NoResultsError, OllamaModelNotFoundError, OllamaUnavailableError

OLLAMA_URL = "http://localhost:11434"
_PROBE_TIMEOUT = 2.0
_GENERATE_TIMEOUT = 120.0


@dataclass(frozen=True)
class Availability:
    available: bool
    model: str
    reason: str | None = None

    def as_dict(self) -> dict:
        payload = {"available": self.available, "model": self.model}
        if self.reason:
            payload["reason"] = self.reason
        return payload


def check_availability(model: str) -> Availability:
    """Report whether summarization can be offered. Never raises."""
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
            response = client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            installed = {m.get("name", "") for m in response.json().get("models", [])}
    except Exception:
        return Availability(
            available=False,
            model=model,
            reason="Ollama is not running. Start it with `ollama serve` to enable summaries. "
            "Search works without it.",
        )

    # Ollama reports tagged names like 'llama3.2:latest'; accept the bare name too.
    if not any(name == model or name.split(":")[0] == model for name in installed):
        return Availability(
            available=False,
            model=model,
            reason=f"The model '{model}' is not installed in Ollama. Run `ollama pull {model}` "
            "to enable summaries. Search works without it.",
        )

    return Availability(available=True, model=model)


def build_prompt(query: str, passages: list[dict]) -> str:
    """Assemble the prompt from the query and passages only (FR-020).

    Deliberately a pure function so a test can assert exactly what would be sent.
    """
    numbered = "\n\n".join(
        f"[{passage.get('rank', index)}] From {passage.get('document_name', 'a document')}:\n"
        f"{passage.get('snippet', '')}"
        for index, passage in enumerate(passages, start=1)
    )
    return (
        "You are helping someone understand passages found in their own documents.\n"
        "Using only the passages below, answer the question in plain language. "
        "If the passages do not answer it, say so plainly rather than guessing.\n\n"
        f"Question: {query}\n\n"
        f"Passages:\n{numbered}\n\n"
        "Answer:"
    )


def summarize(query: str, passages: list[dict], model: str) -> dict:
    """Generate a summary. Raises typed errors the API maps to 503s."""
    if not passages:
        raise NoResultsError("There are no results to summarise. Run a search first.")

    availability = check_availability(model)
    if not availability.available:
        reason = availability.reason or "Ollama is unavailable."
        if "not installed" in reason:
            raise OllamaModelNotFoundError(reason)
        raise OllamaUnavailableError(reason)

    payload = {
        "model": model,
        "prompt": build_prompt(query, passages),
        "stream": False,
    }

    try:
        with httpx.Client(timeout=_GENERATE_TIMEOUT) as client:
            response = client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        raise OllamaUnavailableError(
            f"Ollama rejected the request ({exc.response.status_code}). Check that "
            f"'{model}' is working with `ollama run {model}`. Your search results are "
            "unaffected."
        ) from exc
    except Exception as exc:
        raise OllamaUnavailableError(
            f"Could not reach Ollama: {exc}. Start it with `ollama serve`. Your search "
            "results are unaffected."
        ) from exc

    return {
        "summary": (body.get("response") or "").strip(),
        "model": model,
        "source_ranks": [p.get("rank") for p in passages if p.get("rank") is not None],
    }
