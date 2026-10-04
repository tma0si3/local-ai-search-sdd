"""Unit tests for chunking (T007). Pure function, so no fixtures beyond strings."""

from __future__ import annotations

import pytest

from localsearch.chunk import CHUNK_OVERLAP, CHUNK_SIZE, chunk_text


def test_empty_input_produces_no_chunks():
    assert chunk_text("") == []


def test_whitespace_only_input_produces_no_chunks():
    # This is what makes a text file of blank lines `skipped` rather than `indexed`
    # with zero chunks (data-model.md, Document).
    assert chunk_text("   \n\n  \t \n ") == []


def test_input_shorter_than_one_chunk_is_a_single_chunk():
    text = "A short note about soil erosion."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(text)


def test_chunks_respect_the_size_bound():
    text = "word " * 2000
    for chunk in chunk_text(text):
        assert chunk.char_end - chunk.char_start <= CHUNK_SIZE


def test_consecutive_chunks_overlap():
    text = "word " * 2000
    chunks = chunk_text(text)
    assert len(chunks) > 1
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.char_start < previous.char_end, "chunks must overlap, not abut"


def test_offsets_are_ordered_and_non_degenerate():
    text = "word " * 2000
    chunks = chunk_text(text)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.char_start > previous.char_start
    for chunk in chunks:
        assert chunk.char_start < chunk.char_end


def test_whole_document_is_covered():
    # Overlapping chunks must still cover the document end to end; a gap would mean a
    # passage that can never be found.
    text = "word " * 2000
    chunks = chunk_text(text)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.char_start <= previous.char_end


def test_paragraph_boundary_is_preferred_when_one_is_nearby():
    first = "A" * 900
    second = "B" * 900
    text = f"{first}\n\n{second}"
    chunks = chunk_text(text)
    # The cut should land on the paragraph break rather than mid-run of As.
    assert chunks[0].text == first


def test_dense_paragraph_breaks_still_terminate():
    # Regression guard: a boundary landing earlier than the previous start could stall
    # the loop. This input is deliberately hostile.
    text = ("x\n\n" * 2000)
    chunks = chunk_text(text)
    assert len(chunks) > 0
    assert chunks[-1].char_end == len(text)


def test_custom_size_and_overlap_are_honoured():
    text = "z" * 500
    chunks = chunk_text(text, size=100, overlap=20)
    assert all(c.char_end - c.char_start <= 100 for c in chunks)
    assert len(chunks) > 1


@pytest.mark.parametrize(
    ("size", "overlap"),
    [(0, 0), (-1, 0), (100, 100), (100, 150), (100, -1)],
)
def test_invalid_parameters_are_rejected(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("some text", size=size, overlap=overlap)


def test_defaults_are_the_documented_values():
    # research.md §4 states ~1000 with ~150 overlap. If these drift, the research record
    # and the code disagree, so pin them.
    assert CHUNK_SIZE == 1000
    assert CHUNK_OVERLAP == 150
