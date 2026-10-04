"""Splitting extracted text into passages that stand alone as search results.

Pure: no I/O, no globals, no clock. Everything it needs arrives as arguments, which is
what makes T007 cheap to write (Principle VI).

The two constants below are the main search-quality levers. They are named rather than
inlined so SC-002 can be tuned against the fixture corpus without restructuring anything
(research.md §4).
"""

from __future__ import annotations

from dataclasses import dataclass

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

# How far back from the ideal cut we will look for a paragraph break before giving up and
# cutting mid-paragraph. Roughly a third of a chunk: far enough to find most breaks, near
# enough that chunks stay a consistent size.
_BOUNDARY_SEARCH_WINDOW = 300


@dataclass(frozen=True)
class Chunk:
    """A passage plus its offsets into the document's extracted text."""

    text: str
    char_start: int
    char_end: int


def chunk_text(
    text: str,
    *,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split ``text`` into overlapping passages, preferring paragraph boundaries.

    Returns an empty list for empty or whitespace-only input: a document with no text
    produces no chunks, which is what makes it ``skipped`` rather than ``indexed`` with
    zero chunks (data-model.md, Document).
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be non-negative and smaller than size")

    if not text or not text.strip():
        return []

    chunks: list[Chunk] = []
    start = 0
    length = len(text)

    while start < length:
        ideal_end = min(start + size, length)
        end = ideal_end

        # Prefer a paragraph break near the ideal cut, but never one so close to the start
        # that we would make a pathologically small chunk.
        if ideal_end < length:
            window_start = max(start + 1, ideal_end - _BOUNDARY_SEARCH_WINDOW)
            boundary = text.rfind("\n\n", window_start, ideal_end)
            if boundary != -1:
                end = boundary + 2

        passage = text[start:end]
        if passage.strip():
            chunks.append(Chunk(text=passage.strip(), char_start=start, char_end=end))

        if end >= length:
            break

        # Step forward, leaving `overlap` characters behind so a passage that straddles a
        # boundary still appears whole in one chunk.
        next_start = end - overlap
        # Guard against a boundary landing so early that we fail to advance. Without this,
        # a document of densely spaced paragraph breaks could loop forever.
        start = next_start if next_start > start else end

    return chunks
