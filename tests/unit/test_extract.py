"""Unit tests for text extraction (T019)."""

from __future__ import annotations

import pytest

from localsearch.errors import ExtractionError
from localsearch.extract import SUPPORTED_EXTENSIONS, extract_text, file_type_of


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("field-study-2025.pdf", "pdf"),
        ("budget-review.txt", "txt"),
        ("sourdough-notes.md", "md"),
        ("nested/deeper/kickoff-meeting.docx", "docx"),
    ],
)
def test_each_supported_format_yields_text(corpus, filename, expected):
    path = corpus / filename
    assert file_type_of(path) == expected
    assert extract_text(path).strip()


def test_pdf_text_is_actually_readable(corpus):
    text = extract_text(corpus / "field-study-2025.pdf")
    assert "erosion" in text.lower()


def test_docx_text_is_actually_readable(corpus):
    text = extract_text(corpus / "nested" / "deeper" / "kickoff-meeting.docx")
    assert "prototype" in text.lower()


def test_markdown_is_kept_as_raw_text(corpus):
    # research.md §3: no parser, syntax markers survive. If this changes, the research
    # record is wrong.
    assert "##" in extract_text(corpus / "sourdough-notes.md")


def test_unsupported_type_names_the_supported_ones(corpus):
    with pytest.raises(ExtractionError) as caught:
        extract_text(corpus / "notes.pages")
    message = caught.value.message
    assert ".pages" in message
    # FR-027: say what the user can do, not just what failed.
    assert "PDF" in message and "Word" in message


def test_empty_file_is_an_error_with_a_reason(corpus):
    with pytest.raises(ExtractionError) as caught:
        extract_text(corpus / "empty.txt")
    assert caught.value.message.strip()


def test_whitespace_only_file_is_an_error(corpus):
    with pytest.raises(ExtractionError):
        extract_text(corpus / "whitespace-only.txt")


def test_scanned_pdf_guidance_mentions_ocr(corpus):
    # A user whose scanned PDFs are all skipped needs to know why, and that it is expected.
    with pytest.raises(ExtractionError) as caught:
        extract_text(corpus / "empty.txt")
    assert "OCR" in caught.value.message


def test_unreadable_file_raises_rather_than_crashing(tmp_path):
    path = tmp_path / "locked.txt"
    path.write_text("secret", encoding="utf-8")
    path.chmod(0o000)
    try:
        with pytest.raises(ExtractionError):
            extract_text(path)
    finally:
        path.chmod(0o644)


def test_missing_file_raises_extraction_error(tmp_path):
    with pytest.raises(ExtractionError):
        extract_text(tmp_path / "does-not-exist.txt")


def test_corrupt_pdf_is_an_extraction_error_not_a_crash(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is definitely not a PDF")
    with pytest.raises(ExtractionError):
        extract_text(path)


def test_extension_matching_is_case_insensitive(tmp_path):
    path = tmp_path / "SHOUTING.TXT"
    path.write_text("content here", encoding="utf-8")
    assert file_type_of(path) == "txt"


def test_the_four_documented_formats_are_the_supported_ones():
    assert set(SUPPORTED_EXTENSIONS) == {".pdf", ".txt", ".md", ".docx"}
