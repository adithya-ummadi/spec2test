"""Utility helpers for file type detection and safe byte reading."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

# Mapping from normalised extension to a canonical format tag.
_EXT_TO_FORMAT: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "markdown",
    ".markdown": "markdown",
}

# Mapping from MIME type to format tag (fallback when extension is absent).
_MIME_TO_FORMAT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
}

SUPPORTED_FORMATS: frozenset[str] = frozenset(_EXT_TO_FORMAT.values())


def detect_file_format(filename: str, mime_type: str | None = None) -> str:
    """Return the canonical format tag for *filename*.

    Checks the file extension first; falls back to *mime_type* if provided.

    Returns one of: ``"pdf"``, ``"docx"``, ``"txt"``, ``"markdown"``.

    Raises :class:`ValueError` if the format cannot be determined or is not
    supported.
    """
    ext = Path(filename).suffix.lower()
    if ext in _EXT_TO_FORMAT:
        return _EXT_TO_FORMAT[ext]

    if mime_type:
        # Strip parameters such as "; charset=utf-8"
        base_mime = mime_type.split(";")[0].strip().lower()
        if base_mime in _MIME_TO_FORMAT:
            return _MIME_TO_FORMAT[base_mime]

    raise ValueError(
        f"Unsupported or unrecognisable file type: filename={filename!r}, "
        f"mime_type={mime_type!r}. "
        f"Supported extensions: {sorted(_EXT_TO_FORMAT.keys())}"
    )


def read_file_bytes(path: str | os.PathLike) -> bytes:
    """Read *path* and return its contents as bytes.

    Raises :class:`FileNotFoundError` if the file does not exist, or
    :class:`IOError` for other OS-level errors.
    """
    with open(path, "rb") as fh:
        return fh.read()
