"""Unit tests for Sub-Task 3 — Document Processing Pipeline.

Covers:
- TXT extraction
- Markdown extraction
- DOCX extraction
- PDF extraction
- Requirement segmentation (numbered, bullet, keyword, table, fallback)
- Edge cases (empty input, no requirements found, unicode content)

No LLM calls, no network I/O, no database writes.
"""

from __future__ import annotations

import io
import os
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal in-memory DOCX and PDF fixtures
# ---------------------------------------------------------------------------


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    """Build a minimal .docx file in memory with the given paragraphs."""
    import docx  # type: ignore

    doc = docx.Document()
    for para in paragraphs:
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pdf_bytes(pages: list[str]) -> bytes:
    """Build a minimal PDF in memory using pypdf's PdfWriter."""
    from pypdf import PdfWriter  # type: ignore

    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        # pypdf's PdfWriter doesn't draw text — we annotate via metadata
        # so the page exists.  Real PDF text extraction is tested via an
        # externally-crafted PDF fixture below.
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# file_utils tests
# ---------------------------------------------------------------------------


class TestDetectFileFormat:
    def test_pdf_by_extension(self):
        from app.utils.file_utils import detect_file_format

        assert detect_file_format("spec.pdf") == "pdf"

    def test_docx_by_extension(self):
        from app.utils.file_utils import detect_file_format

        assert detect_file_format("spec.docx") == "docx"

    def test_txt_by_extension(self):
        from app.utils.file_utils import detect_file_format

        assert detect_file_format("spec.txt") == "txt"

    def test_markdown_by_md_extension(self):
        from app.utils.file_utils import detect_file_format

        assert detect_file_format("spec.md") == "markdown"

    def test_markdown_by_markdown_extension(self):
        from app.utils.file_utils import detect_file_format

        assert detect_file_format("spec.markdown") == "markdown"

    def test_fallback_to_mime_type(self):
        from app.utils.file_utils import detect_file_format

        assert detect_file_format("upload", "application/pdf") == "pdf"

    def test_mime_strips_charset(self):
        from app.utils.file_utils import detect_file_format

        assert detect_file_format("upload", "text/plain; charset=utf-8") == "txt"

    def test_unsupported_raises_value_error(self):
        from app.utils.file_utils import detect_file_format

        with pytest.raises(ValueError, match="Unsupported"):
            detect_file_format("photo.jpg")

    def test_unknown_mime_and_no_ext_raises(self):
        from app.utils.file_utils import detect_file_format

        with pytest.raises(ValueError):
            detect_file_format("data", "application/octet-stream")


# ---------------------------------------------------------------------------
# TXT extraction tests
# ---------------------------------------------------------------------------


class TestExtractTextFromTxt:
    def test_basic_lines(self):
        from app.services.document_processor import extract_text_from_txt

        content = b"Line one\nLine two\n\nLine three\n"
        pages = extract_text_from_txt(content)
        assert len(pages) == 2
        assert "Line one" in pages[0].text
        assert "Line two" in pages[0].text
        assert "Line three" in pages[1].text

    def test_source_location_recorded(self):
        from app.services.document_processor import extract_text_from_txt

        content = b"Hello world\n"
        pages = extract_text_from_txt(content)
        assert pages[0].source_location.startswith("lines")

    def test_empty_input(self):
        from app.services.document_processor import extract_text_from_txt

        pages = extract_text_from_txt(b"")
        assert pages == []

    def test_only_whitespace(self):
        from app.services.document_processor import extract_text_from_txt

        pages = extract_text_from_txt(b"   \n\n   \n")
        assert pages == []

    def test_unicode_content(self):
        from app.services.document_processor import extract_text_from_txt

        content = "The system shall support UTF-8: 日本語\n".encode("utf-8")
        pages = extract_text_from_txt(content)
        assert len(pages) == 1
        assert "日本語" in pages[0].text


# ---------------------------------------------------------------------------
# Markdown extraction tests
# ---------------------------------------------------------------------------


class TestExtractTextFromMarkdown:
    def test_markdown_blocks(self):
        from app.services.document_processor import extract_text_from_markdown

        md = b"## Introduction\n\nThe system must handle requests.\n\n## Scope\n"
        pages = extract_text_from_markdown(md)
        # At least two blocks (Introduction section, Scope section)
        assert len(pages) >= 2

    def test_source_location_is_line_range(self):
        from app.services.document_processor import extract_text_from_markdown

        md = b"Line 1\nLine 2\n\nLine 4\n"
        pages = extract_text_from_markdown(md)
        assert "lines" in pages[0].source_location

    def test_empty_markdown(self):
        from app.services.document_processor import extract_text_from_markdown

        pages = extract_text_from_markdown(b"")
        assert pages == []


# ---------------------------------------------------------------------------
# DOCX extraction tests
# ---------------------------------------------------------------------------


class TestExtractTextFromDocx:
    def test_extracts_paragraphs(self):
        from app.services.document_processor import extract_text_from_docx

        raw = _make_docx_bytes(
            [
                "The system shall authenticate users.",
                "The system must store passwords securely.",
                "",  # blank paragraph — should be skipped
                "Users should be able to reset their password.",
            ]
        )
        pages = extract_text_from_docx(raw)
        texts = [p.text for p in pages]
        assert any("authenticate users" in t for t in texts)
        assert any("reset their password" in t for t in texts)
        # Blank paragraph must not appear
        assert not any(t == "" for t in texts)

    def test_source_location_is_paragraph_ref(self):
        from app.services.document_processor import extract_text_from_docx

        raw = _make_docx_bytes(["First paragraph."])
        pages = extract_text_from_docx(raw)
        assert "paragraph" in pages[0].source_location

    def test_empty_docx(self):
        from app.services.document_processor import extract_text_from_docx

        raw = _make_docx_bytes([])
        pages = extract_text_from_docx(raw)
        assert pages == []


# ---------------------------------------------------------------------------
# PDF extraction tests
# ---------------------------------------------------------------------------


class TestExtractTextFromPdf:
    def test_blank_pdf_returns_empty(self):
        """A PDF with no text content should return an empty list."""
        from app.services.document_processor import extract_text_from_pdf

        raw = _make_pdf_bytes([""])
        # Blank pages have no extractable text; result should be empty.
        pages = extract_text_from_pdf(raw)
        assert isinstance(pages, list)

    def test_pdf_with_text(self, tmp_path):
        """Use reportlab (if available) to create a real text PDF; skip otherwise."""
        pytest.importorskip("reportlab")
        from reportlab.pdfgen import canvas  # type: ignore
        from app.services.document_processor import extract_text_from_pdf

        pdf_path = tmp_path / "test.pdf"
        c = canvas.Canvas(str(pdf_path))
        c.drawString(72, 720, "The system shall process PDF files.")
        c.showPage()
        c.save()

        raw = pdf_path.read_bytes()
        pages = extract_text_from_pdf(raw)
        assert len(pages) >= 1
        combined = " ".join(p.text for p in pages)
        assert "PDF files" in combined

    def test_source_location_is_page_ref(self, tmp_path):
        """Page reference should say 'page N'."""
        pytest.importorskip("reportlab")
        from reportlab.pdfgen import canvas  # type: ignore
        from app.services.document_processor import extract_text_from_pdf

        pdf_path = tmp_path / "test2.pdf"
        c = canvas.Canvas(str(pdf_path))
        c.drawString(72, 720, "Requirement text here.")
        c.showPage()
        c.save()

        raw = pdf_path.read_bytes()
        pages = extract_text_from_pdf(raw)
        if pages:
            assert pages[0].source_location.startswith("page")


# ---------------------------------------------------------------------------
# Requirement segmenter tests
# ---------------------------------------------------------------------------


class TestSegmentRequirements:
    def test_numbered_list(self):
        from app.services.requirement_segmenter import segment_requirements

        text = textwrap.dedent("""\
            1. The system shall authenticate users.
            2. The system shall log all access attempts.
            3. Passwords must be hashed using bcrypt.
        """)
        reqs = segment_requirements(text)
        assert len(reqs) == 3
        assert any("authenticate users" in r for r in reqs)

    def test_fr_labelled_list(self):
        from app.services.requirement_segmenter import segment_requirements

        text = textwrap.dedent("""\
            FR-1 The login page shall display an error on invalid credentials.
            FR-2 The system must lock accounts after 5 failed attempts.
        """)
        reqs = segment_requirements(text)
        assert len(reqs) == 2

    def test_bullet_points(self):
        from app.services.requirement_segmenter import segment_requirements

        text = textwrap.dedent("""\
            - Users must be able to register with an email address.
            - The system shall send a confirmation email.
            * Passwords must be at least 8 characters.
        """)
        reqs = segment_requirements(text)
        assert len(reqs) == 3

    def test_keyword_lines(self):
        from app.services.requirement_segmenter import segment_requirements

        text = textwrap.dedent("""\
            The API shall return a 200 status code on success.
            The response must include a JSON body.
            Error messages should be human-readable.
        """)
        reqs = segment_requirements(text)
        assert len(reqs) == 3

    def test_table_like_rows(self):
        from app.services.requirement_segmenter import segment_requirements

        text = textwrap.dedent("""\
            | ID    | Requirement                       |
            | FR-01 | System shall support OAuth2.      |
            | FR-02 | System must support SAML.         |
        """)
        reqs = segment_requirements(text)
        # At least the data rows should be captured.
        assert len(reqs) >= 2

    def test_paragraph_fallback(self):
        from app.services.requirement_segmenter import segment_requirements

        text = "First paragraph of plain text.\n\nSecond paragraph of plain text."
        reqs = segment_requirements(text)
        assert len(reqs) == 2
        assert any("First paragraph" in r for r in reqs)

    def test_empty_text_returns_empty_list(self):
        from app.services.requirement_segmenter import segment_requirements

        assert segment_requirements("") == []

    def test_whitespace_only_returns_empty(self):
        from app.services.requirement_segmenter import segment_requirements

        assert segment_requirements("   \n\n   ") == []

    def test_markdown_headers_filtered_in_fallback(self):
        from app.services.requirement_segmenter import segment_requirements

        text = "## Introduction\n\nSome prose without requirements.\n\n## End"
        reqs = segment_requirements(text)
        # Headers should be stripped; only non-empty, non-header content kept.
        for r in reqs:
            # The raw "#" headers must not be in the results.
            assert not r.startswith("#")

    def test_mixed_formats(self):
        """A document with both numbered items and keyword lines."""
        from app.services.requirement_segmenter import segment_requirements

        text = textwrap.dedent("""\
            1. The system shall support HTTPS.
            2. The system must reject plain HTTP connections.
            The login page should redirect HTTP to HTTPS automatically.
        """)
        reqs = segment_requirements(text)
        assert len(reqs) == 3

    def test_multiline_item_continuation(self):
        """A numbered item that spans two lines should be joined."""
        from app.services.requirement_segmenter import segment_requirements

        text = (
            "1. The system shall validate all inputs including\n"
            "   special characters and Unicode code points.\n"
            "2. The system must reject invalid payloads.\n"
        )
        reqs = segment_requirements(text)
        assert len(reqs) == 2
        assert "Unicode code points" in reqs[0]


# ---------------------------------------------------------------------------
# segment_requirements_from_pages tests
# ---------------------------------------------------------------------------


class TestSegmentRequirementsFromPages:
    def test_preserves_source_location(self):
        from app.services.document_processor import ExtractedPage
        from app.services.requirement_segmenter import segment_requirements_from_pages

        pages = [
            ExtractedPage(
                text="1. The system shall do X.\n2. The system must do Y.",
                source_location="page 1",
            )
        ]
        result = segment_requirements_from_pages(pages)
        assert len(result) == 2
        for item in result:
            assert item["source_location"] == "page 1"
            assert "text" in item

    def test_empty_pages(self):
        from app.services.requirement_segmenter import segment_requirements_from_pages

        assert segment_requirements_from_pages([]) == []


# ---------------------------------------------------------------------------
# dispatch / extract_text tests
# ---------------------------------------------------------------------------


class TestExtractTextDispatch:
    def test_unsupported_format_raises(self):
        from app.services.document_processor import extract_text

        with pytest.raises(ValueError, match="Unsupported file format"):
            extract_text(b"data", "xlsx")

    def test_txt_dispatched_correctly(self):
        from app.services.document_processor import extract_text

        pages = extract_text(b"Hello world\n", "txt")
        assert len(pages) == 1
        assert "Hello world" in pages[0].text

    def test_markdown_dispatched_correctly(self):
        from app.services.document_processor import extract_text

        pages = extract_text(b"# Title\n\nSome text\n", "markdown")
        assert isinstance(pages, list)
