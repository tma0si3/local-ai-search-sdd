"""Query execution: embed, rank, join back to documents.

Thin by design. The ranking is in `search.py` (pure), the storage in `store.py`; this just
joins them. Kept out of `indexer.py` so searching does not depend on indexing.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import embed, search, store
from .errors import EmptyQueryError, ModelMismatchError, NoIndexError

MAX_LIMIT = 50
DEFAULT_LIMIT = 10

MIN_RELEVANCE_SCORE = 0.10
"""Below this cosine score, a passage is not shown at all.

Without a floor, FR-016's "no relevant results" state could never occur: ranking the whole
corpus always yields a top ten, so a question about something the user has never written
about would return ten unrelated passages presented as matches.

Measured on the fixture corpus:

* direct answers to a question      0.30 - 0.55
* a single relevant sentence buried
  in a long, repetitive document    ~0.19   <- the case that sets the floor
* an unrelated query                ~0.03, sometimes negative

0.10 sits below the diluted-needle case and well above the noise. An earlier value of 0.15
looked reasonable against ordinary documents but suppressed the buried-sentence case
entirely, which is precisely the search a user cannot perform by hand and therefore the
one worth protecting.

This is a product judgement, not a mathematical one: showing nothing is more honest than
showing noise, but suppressing a real answer is worse than either.
"""


@dataclass(frozen=True)
class SearchResult:
    rank: int
    document_name: str
    document_relative_path: str
    document_path: str
    snippet: str
    score: float

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "document_name": self.document_name,
            "document_relative_path": self.document_relative_path,
            "document_path": self.document_path,
            "snippet": self.snippet,
            "score": round(self.score, 4),
        }


def run_search(query: str, limit: int = DEFAULT_LIMIT) -> list[SearchResult]:
    """Return ranked passages. An empty list is a valid answer, not an error (FR-016)."""
    if not query or not query.strip():
        raise EmptyQueryError("Enter something to search for.")

    meta = store.load_meta()
    if meta is None:
        raise NoIndexError(
            "No documents have been indexed yet. Choose a folder and run indexing first."
        )

    if meta.embedding_model != embed.model_name():
        raise ModelMismatchError(
            "This index was built with a different embedding model, so its results would "
            "be meaningless. Re-index your folder to search it again."
        )

    limit = max(1, min(int(limit), MAX_LIMIT))

    matrix = store.load_matrix()
    ranked = search.rank(embed.embed_query(query.strip()), matrix, limit=limit)
    if not ranked:
        return []

    records = store.load_chunks_by_rows([row for row, _ in ranked])

    results: list[SearchResult] = []
    for row, score in ranked:
        # Stop at the first passage below the floor; ranked is already descending, so
        # everything after it is worse (FR-016).
        if score < MIN_RELEVANCE_SCORE:
            break
        record = records.get(row)
        if record is None:
            # Index and matrix disagree. Skip rather than crash the query; the pair is
            # written atomically, so this should be unreachable.
            continue
        results.append(
            SearchResult(
                rank=len(results) + 1,
                document_name=record.document_name,
                document_relative_path=record.document_relative_path,
                document_path=record.document_path,
                # The passage is shown in full as stored, so it is understandable without
                # opening the source document (US2 scenario 5).
                snippet=record.text,
                score=score,
            )
        )
    return results
