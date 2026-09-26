"""Deterministic requirement segmenter.

Converts raw extracted text (or a list of :class:`ExtractedPage` objects)
into individual requirement strings using heuristic pattern matching.

NO LLM is used here — all logic is rule-based and deterministic.

Recognised patterns (in priority order):
1. Numbered items       — ``1.``, ``1)``, ``FR-1``, ``REQ-001``, ``R1.``
2. Bullet points        — ``-``, ``*``, ``•``, ``+`` at line start
3. Keyword lines        — lines containing "shall", "must", or "should"
4. Table-like rows      — lines containing two or more ``|`` characters
5. Paragraph fallback   — double-newline-separated blocks
"""

from __future__ import annotations

import re
from typing import List

from app.services.document_processor import ExtractedPage


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Numbered list: "1.", "1)", "1.1", "FR-1", "REQ-001", "R1."
_RE_NUMBERED = re.compile(
    r"^(?:"
    r"(?:FR|REQ|REQ\.|SRS|UC|R|NFR)-?\d+[\d.]*"  # labelled: FR-1, REQ-001
    r"|"
    r"\d+(?:\.\d+)*[.)]\s"                          # numeric: 1. / 1) / 1.2.
    r")",
    re.IGNORECASE,
)

# Bullet point: -, *, •, + at the start of a (possibly indented) line.
_RE_BULLET = re.compile(r"^\s*[-*•+]\s+")

# Keyword: "shall", "must", "should" as whole words anywhere in the line.
_RE_KEYWORD = re.compile(r"\b(?:shall|must|should)\b", re.IGNORECASE)

# Table row: two or more pipe characters.
_RE_TABLE_ROW = re.compile(r"\|[^|]+\|")


# ---------------------------------------------------------------------------
# Core segmenter
# ---------------------------------------------------------------------------


def segment_requirements(text: str) -> List[str]:
    """Segment *text* into individual requirement strings.

    Strategy:
    1. Split the input into lines.
    2. Classify each line into one of the recognised patterns.
    3. Accumulate multi-line items (continuation lines that belong to the
       current item are joined until the next item boundary is found).
    4. Fall back to paragraph splitting (double blank lines) if fewer than
       two structured items were found in the text.

    Returns a list of non-empty, stripped requirement strings.
    """
    lines = text.splitlines()

    # --- Pass 1: classify each line ---
    # Each entry is (is_item_start: bool, line: str)
    classified: list[tuple[bool, str]] = []
    for line in lines:
        stripped = line.strip()
        is_start = bool(
            _RE_NUMBERED.match(stripped)
            or _RE_BULLET.match(line)
            or _RE_KEYWORD.search(stripped)
            or _RE_TABLE_ROW.search(stripped)
        )
        classified.append((is_start, stripped))

    # Count structured starts.
    structured_count = sum(1 for is_start, _ in classified if is_start)

    if structured_count >= 2:
        return _merge_structured(classified)

    # --- Fallback: paragraph segmentation ---
    return _paragraph_fallback(text)


def _merge_structured(classified: list[tuple[bool, str]]) -> List[str]:
    """Merge classified lines into requirement strings.

    A new requirement starts whenever ``is_start`` is True.  Continuation
    lines (non-empty, non-start) are appended to the current item.  Empty
    lines act as separators — they end the current item.
    """
    results: list[str] = []
    current_parts: list[str] = []

    for is_start, line in classified:
        if is_start:
            if current_parts:
                results.append(" ".join(current_parts))
            current_parts = [line]
        elif line:
            # Non-empty continuation line — append to current item.
            current_parts.append(line)
        else:
            # Empty line — flush current item.
            if current_parts:
                results.append(" ".join(current_parts))
                current_parts = []

    if current_parts:
        results.append(" ".join(current_parts))

    return [r for r in results if r.strip()]


def _paragraph_fallback(text: str) -> List[str]:
    """Split *text* on two or more consecutive blank lines."""
    paragraphs = re.split(r"\n{2,}", text)
    cleaned = []
    for para in paragraphs:
        para = para.strip()
        # Remove Markdown section headers (e.g., "## Section 1") as they are
        # structural noise, not requirements — unless the line also contains a
        # keyword.
        lines = para.splitlines()
        filtered = [
            ln for ln in lines
            if not re.match(r"^#{1,6}\s", ln) or _RE_KEYWORD.search(ln)
        ]
        result = " ".join(ln.strip() for ln in filtered if ln.strip())
        if result:
            cleaned.append(result)
    return cleaned


# ---------------------------------------------------------------------------
# Convenience wrapper that accepts ExtractedPage objects
# ---------------------------------------------------------------------------


def segment_requirements_from_pages(pages: List[ExtractedPage]) -> List[dict]:
    """Convert a list of :class:`ExtractedPage` objects into requirement dicts.

    Each returned dict has keys:
    - ``text``            — the requirement string
    - ``source_location`` — the originating page/line reference

    This is the entry-point used by :class:`DocumentService`.
    """
    results: list[dict] = []
    for page in pages:
        reqs = segment_requirements(page.text)
        for req_text in reqs:
            results.append(
                {
                    "text": req_text,
                    "source_location": page.source_location,
                }
            )
    return results
