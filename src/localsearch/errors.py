"""Typed errors carrying contract codes and actionable messages (FR-027).

Every message states what failed *and* what the user can do about it. An error that only
says what went wrong leaves the user stuck, which is the thing Principle VIII is about.
"""

from __future__ import annotations


class LocalSearchError(Exception):
    """Base class. Carries an HTTP status and a contract error code."""

    code = "INTERNAL_ERROR"
    status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# --- Configuration and paths -------------------------------------------------


class InvalidPathError(LocalSearchError):
    code = "INVALID_PATH"
    status = 400


class PathNotFoundError(LocalSearchError):
    code = "PATH_NOT_FOUND"
    status = 404


class PathNotReadableError(LocalSearchError):
    code = "PATH_NOT_READABLE"
    status = 403


class PathOutOfScopeError(LocalSearchError):
    code = "PATH_OUT_OF_SCOPE"
    status = 403


class FileNotFoundInIndexError(LocalSearchError):
    code = "FILE_NOT_FOUND"
    status = 404


class NotConfiguredError(LocalSearchError):
    code = "NOT_CONFIGURED"
    status = 400


# --- Indexing and search -----------------------------------------------------


class EmptyQueryError(LocalSearchError):
    code = "EMPTY_QUERY"
    status = 400


class NoIndexError(LocalSearchError):
    code = "NO_INDEX"
    status = 409


class ModelMismatchError(LocalSearchError):
    code = "MODEL_MISMATCH"
    status = 409


class EmbeddingModelUnavailableError(LocalSearchError):
    """Model weights are not present locally and we refuse to fetch mid-operation."""

    code = "EMBEDDING_MODEL_UNAVAILABLE"
    status = 503


class ExtractionError(LocalSearchError):
    """A single document could not be read. Carries the skip reason shown to the user.

    This is never fatal to an indexing run: it is recorded against the document and the
    run continues (FR-011).
    """

    code = "EXTRACTION_FAILED"
    status = 422


# --- Summarization -----------------------------------------------------------


class NoResultsError(LocalSearchError):
    code = "NO_RESULTS"
    status = 400


class OllamaUnavailableError(LocalSearchError):
    code = "OLLAMA_UNAVAILABLE"
    status = 503


class OllamaModelNotFoundError(LocalSearchError):
    code = "MODEL_NOT_FOUND"
    status = 503
