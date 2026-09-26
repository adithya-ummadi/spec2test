"""DocumentService — orchestrates upload processing.

Ties together file-type detection, text extraction, requirement segmentation,
and persistence into SQLite so that higher layers (routers) have a single
call to make.

This service is intentionally simple: it performs all work synchronously
inside an async wrapper so it can be awaited by FastAPI route handlers.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import DocumentModel, RequirementModel
from app.services.document_processor import extract_text
from app.services.requirement_segmenter import segment_requirements_from_pages
from app.utils.file_utils import detect_file_format


async def process_upload(
    db: AsyncSession,
    filename: str,
    file_bytes: bytes,
    mime_type: str | None = None,
) -> DocumentModel:
    """Process an uploaded file end-to-end and persist the results.

    1. Detect the file format.
    2. Extract text pages from the file.
    3. Segment each page into individual requirement strings.
    4. Persist a :class:`DocumentModel` and one :class:`RequirementModel`
       per extracted requirement, all with status ``RAW``.
    5. Return the persisted :class:`DocumentModel`.

    The caller is responsible for committing (or rolling back) the session.
    """
    # Step 1 — detect format
    file_format = detect_file_format(filename, mime_type)

    # Step 2 — extract text
    pages = extract_text(file_bytes, file_format)

    # Step 3 — segment requirements
    req_dicts = segment_requirements_from_pages(pages)

    # Step 4 — persist
    doc = DocumentModel(filename=filename, status="PROCESSING")
    db.add(doc)
    await db.flush()  # Obtain doc.id without committing.

    for item in req_dicts:
        req = RequirementModel(
            document_id=doc.id,
            text=item["text"],
            source_location=item.get("source_location"),
            status="RAW",
        )
        db.add(req)

    doc.status = "PROCESSED"
    await db.flush()

    return doc
