"""Deterministic text extraction from PDF, DOCX, TXT, and Markdown files.

Each extractor returns a list of :class:`ExtractedPage` objects so that
source location (page number or line range) is preserved for traceability.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Data transfer object
# ---------------------------------------------------------------------------


@dataclass
class ExtractedPage:
    """One logical unit of extracted text with its origin."""

    text: str
    # Human-readable source location, e.g. "page 1" or "lines 1-20".
    source_location: str = ""


# ---------------------------------------------------------------------------
# PDF extraction  (pypdf)
# ---------------------------------------------------------------------------


def extract_text_from_pdf(file_bytes: bytes) -> List[ExtractedPage]:
    """Extract text from a PDF byte string, one :class:`ExtractedPage` per page.

    Requires ``pypdf`` (listed in requirements.txt).
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "pypdf is required for PDF extraction. "
            "Install it with: pip install pypdf"
        ) from exc

    reader = PdfReader(io.BytesIO(file_bytes))
    pages: List[ExtractedPage] = []
    for page_num, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        text = raw.strip()
        if text:
            pages.append(ExtractedPage(text=text, source_location=f"page {page_num}"))
    return pages


# ---------------------------------------------------------------------------
# DOCX extraction  (python-docx)
# ---------------------------------------------------------------------------


def extract_text_from_docx(file_bytes: bytes) -> List[ExtractedPage]:
    """Extract text from a DOCX byte string.

    Returns one :class:`ExtractedPage` per non-empty paragraph so that
    paragraph indices can serve as approximate source locations.

    Requires ``python-docx`` (listed in requirements.txt).
    """
    try:
        import docx  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "python-docx is required for DOCX extraction. "
            "Install it with: pip install python-docx"
        ) from exc

    document = docx.Document(io.BytesIO(file_bytes))
    pages: List[ExtractedPage] = []
    for para_num, para in enumerate(document.paragraphs, start=1):
        text = para.text.strip()
        if text:
            pages.append(
                ExtractedPage(text=text, source_location=f"paragraph {para_num}")
            )
    return pages


# ---------------------------------------------------------------------------
# TXT / Markdown extraction
# ---------------------------------------------------------------------------


def extract_text_from_txt(file_bytes: bytes) -> List[ExtractedPage]:
    """Decode *file_bytes* as UTF-8 and return one page per non-empty line block.

    Consecutive non-empty lines are grouped together into a single
    :class:`ExtractedPage` whose ``source_location`` records the line range.
    This preserves enough fidelity for the segmenter while keeping the list
    size manageable.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()

    pages: List[ExtractedPage] = []
    block_lines: list[str] = []
    block_start: int = 1

    for line_num, line in enumerate(lines, start=1):
        if line.strip():
            if not block_lines:
                block_start = line_num
            block_lines.append(line)
        else:
            if block_lines:
                pages.append(
                    ExtractedPage(
                        text="\n".join(block_lines),
                        source_location=f"lines {block_start}-{line_num - 1}",
                    )
                )
                block_lines = []

    # Flush the last block.
    if block_lines:
        pages.append(
            ExtractedPage(
                text="\n".join(block_lines),
                source_location=f"lines {block_start}-{len(lines)}",
            )
        )

    return pages


# extract_text_from_markdown is identical to extract_text_from_txt — reuse it.
extract_text_from_markdown = extract_text_from_txt


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def extract_text(file_bytes: bytes, file_format: str) -> List[ExtractedPage]:
    """Route *file_bytes* to the correct extractor based on *file_format*.

    *file_format* must be one of ``"pdf"``, ``"docx"``, ``"txt"``,
    ``"markdown"``.

    Raises :class:`ValueError` for unsupported formats.
    """
    dispatch = {
        "pdf": extract_text_from_pdf,
        "docx": extract_text_from_docx,
        "txt": extract_text_from_txt,
        "markdown": extract_text_from_markdown,
    }
    if file_format not in dispatch:
        raise ValueError(
            f"Unsupported file format: {file_format!r}. "
            f"Supported: {sorted(dispatch.keys())}"
        )
    return dispatch[file_format](file_bytes)
