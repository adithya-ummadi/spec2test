"""Document router — endpoints under /api/documents."""

from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.db import (
    AcceptanceCriteriaModel,
    DocumentModel,
    FindingModel,
    RefinedRequirementModel,
    RequirementModel,
    TestCaseModel,
)
from app.models.schemas import (
    DocumentUploadResponse,
    FindingSchema,
    RequirementSchema,
    TraceabilityEntry,
)
from app.services.analysis_batch import run_batch_analysis
from app.services.document_service import process_upload
from app.utils.file_utils import detect_file_format

router = APIRouter(prefix="/api/documents", tags=["documents"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def _check_file_type(upload: UploadFile) -> None:
    """Raise HTTP 415 if the file type is not supported."""
    filename = upload.filename or ""
    import pathlib
    ext = pathlib.Path(filename).suffix.lower()
    content_type = (upload.content_type or "").split(";")[0].strip().lower()

    if ext in _ALLOWED_EXTENSIONS:
        return
    if content_type in _ALLOWED_CONTENT_TYPES:
        return
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            f"Unsupported file type: extension={ext!r}, content_type={content_type!r}. "
            "Supported types: .pdf, .docx, .txt, .md, .markdown"
        ),
    )


async def _get_document_or_404(doc_id: int, db: AsyncSession) -> DocumentModel:
    result = await db.execute(
        select(DocumentModel)
        .where(DocumentModel.id == doc_id)
        .options(selectinload(DocumentModel.requirements))
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {doc_id} not found.",
        )
    return doc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a specification document",
)
async def upload_document(
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT, or Markdown file")],
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Accept a specification file, extract requirements, and persist to the DB."""
    _check_file_type(file)

    file_bytes = await file.read()
    filename = file.filename or "upload"

    try:
        doc = await process_upload(
            db=db,
            filename=filename,
            file_bytes=file_bytes,
            mime_type=file.content_type,
        )
        await db.commit()
        await db.refresh(doc)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document processing failed: {exc}",
        ) from exc

    # Query requirement count explicitly to avoid lazy-load issues with async SQLAlchemy.
    req_count_result = await db.execute(
        select(RequirementModel).where(RequirementModel.document_id == doc.id)
    )
    req_count = len(req_count_result.scalars().all())

    return DocumentUploadResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        requirement_count=req_count,
    )


@router.get(
    "",
    response_model=List[DocumentUploadResponse],
    summary="List all uploaded documents",
)
async def list_documents(
    db: AsyncSession = Depends(get_db),
) -> list[DocumentUploadResponse]:
    """Return all documents with their processing status and requirement counts."""
    result = await db.execute(
        select(DocumentModel).options(selectinload(DocumentModel.requirements))
    )
    docs = result.scalars().all()
    return [
        DocumentUploadResponse(
            id=d.id,
            filename=d.filename,
            status=d.status,
            requirement_count=len(d.requirements),
        )
        for d in docs
    ]


@router.get(
    "/{doc_id}",
    response_model=DocumentUploadResponse,
    summary="Get document details",
)
async def get_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Return details for a single document, including requirement count."""
    doc = await _get_document_or_404(doc_id, db)
    return DocumentUploadResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        requirement_count=len(doc.requirements),
    )


@router.get(
    "/{doc_id}/requirements",
    response_model=List[RequirementSchema],
    summary="List requirements for a document",
)
async def list_requirements(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[RequirementSchema]:
    """Return all requirements belonging to the given document."""
    await _get_document_or_404(doc_id, db)
    result = await db.execute(
        select(RequirementModel)
        .where(RequirementModel.document_id == doc_id)
        .order_by(RequirementModel.id)
    )
    reqs = result.scalars().all()
    return [RequirementSchema.model_validate(r) for r in reqs]


@router.post(
    "/{doc_id}/analyze",
    summary="Trigger batch analysis for a document",
)
async def analyze_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run LLM analysis on all RAW requirements belonging to the document."""
    await _get_document_or_404(doc_id, db)
    try:
        batch_result = await run_batch_analysis(db=db, document_id=doc_id)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch analysis failed: {exc}",
        ) from exc

    return {
        "document_id": doc_id,
        "analyzed": batch_result.analyzed,
        "failed": batch_result.failed,
        "skipped": batch_result.skipped,
        "errors": batch_result.errors,
    }


@router.get(
    "/{doc_id}/traceability",
    response_model=List[TraceabilityEntry],
    summary="Get traceability data for a document",
)
async def get_traceability(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[TraceabilityEntry]:
    """Return a traceability entry for every requirement in the document."""
    await _get_document_or_404(doc_id, db)

    result = await db.execute(
        select(RequirementModel)
        .where(RequirementModel.document_id == doc_id)
        .order_by(RequirementModel.id)
    )
    reqs = result.scalars().all()

    entries: list[TraceabilityEntry] = []
    for req in reqs:
        finding_ids = [
            f.id
            for f in (
                await db.execute(
                    select(FindingModel).where(FindingModel.requirement_id == req.id)
                )
            ).scalars().all()
        ]

        refined_row = (
            await db.execute(
                select(RefinedRequirementModel).where(
                    RefinedRequirementModel.requirement_id == req.id
                )
            )
        ).scalar_one_or_none()

        ac_ids = [
            a.id
            for a in (
                await db.execute(
                    select(AcceptanceCriteriaModel).where(
                        AcceptanceCriteriaModel.requirement_id == req.id
                    )
                )
            ).scalars().all()
        ]

        tc_ids = [
            tc.id
            for tc in (
                await db.execute(
                    select(TestCaseModel).where(TestCaseModel.requirement_id == req.id)
                )
            ).scalars().all()
        ]

        entries.append(
            TraceabilityEntry(
                requirement_id=req.id,
                finding_ids=finding_ids,
                refined_requirement_id=refined_row.id if refined_row else None,
                acceptance_criteria_ids=ac_ids,
                test_case_ids=tc_ids,
            )
        )

    return entries
