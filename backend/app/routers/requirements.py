"""Requirements router — endpoints under /api/requirements."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.db import (
    AcceptanceCriteriaModel,
    FindingModel,
    RefinedRequirementModel,
    RequirementModel,
    TestCaseModel,
)
from app.models.schemas import (
    AcceptanceCriteriaSchema,
    FindingSchema,
    RefinedRequirementSchema,
    RequirementSchema,
    TestCaseSchema,
)
from app.services.analyzer import AnalysisError, analyze_requirement
from app.services.refiner import RefinementError, refine_requirement

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_requirement_or_404(req_id: int, db: AsyncSession) -> RequirementModel:
    result = await db.execute(
        select(RequirementModel).where(RequirementModel.id == req_id)
    )
    req = result.scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement {req_id} not found.",
        )
    return req


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{req_id}",
    summary="Get requirement details",
)
async def get_requirement(
    req_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the full detail for one requirement, including its findings."""
    req = await _get_requirement_or_404(req_id, db)

    findings_result = await db.execute(
        select(FindingModel).where(FindingModel.requirement_id == req_id)
    )
    findings = findings_result.scalars().all()

    return {
        "requirement": RequirementSchema.model_validate(req),
        "findings": [FindingSchema.model_validate(f) for f in findings],
    }


@router.post(
    "/{req_id}/analyze",
    summary="Analyze a single requirement",
)
async def analyze_single_requirement(
    req_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run LLM analysis on one requirement and persist the resulting findings."""
    req = await _get_requirement_or_404(req_id, db)

    try:
        findings = await analyze_requirement(req)
    except AnalysisError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Analysis failed: {exc}",
        ) from exc

    for finding in findings:
        db.add(finding)

    req.status = "ANALYZED"

    try:
        await db.commit()
        await db.refresh(req)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist analysis results: {exc}",
        ) from exc

    return {
        "requirement_id": req_id,
        "status": req.status,
        "findings": [FindingSchema.model_validate(f) for f in findings],
    }


@router.post(
    "/{req_id}/refine",
    summary="Refine a requirement and generate test artifacts",
)
async def refine_single_requirement(
    req_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run the refinement pipeline on one requirement and persist all artifacts."""
    req = await _get_requirement_or_404(req_id, db)

    # Load existing findings for this requirement.
    findings_result = await db.execute(
        select(FindingModel).where(FindingModel.requirement_id == req_id)
    )
    findings = findings_result.scalars().all()

    try:
        refined_req, ac, test_cases = await refine_requirement(req, list(findings), db)
        await db.commit()
        await db.refresh(refined_req)
        await db.refresh(ac)
        for tc in test_cases:
            await db.refresh(tc)
    except RefinementError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Refinement failed: {exc}",
        ) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist refinement results: {exc}",
        ) from exc

    return {
        "requirement_id": req_id,
        "status": req.status,
        "refined_requirement": RefinedRequirementSchema.model_validate(refined_req),
        "acceptance_criteria": AcceptanceCriteriaSchema.model_validate(ac),
        "test_cases": [TestCaseSchema.model_validate(tc) for tc in test_cases],
    }


@router.get(
    "/{req_id}/refined",
    summary="Get refined requirement and test artifacts",
)
async def get_refined(
    req_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the refined requirement, acceptance criteria, and test cases."""
    await _get_requirement_or_404(req_id, db)

    refined_result = await db.execute(
        select(RefinedRequirementModel).where(
            RefinedRequirementModel.requirement_id == req_id
        )
    )
    refined_req = refined_result.scalar_one_or_none()

    ac_result = await db.execute(
        select(AcceptanceCriteriaModel).where(
            AcceptanceCriteriaModel.requirement_id == req_id
        )
    )
    ac_rows = ac_result.scalars().all()

    tc_result = await db.execute(
        select(TestCaseModel).where(TestCaseModel.requirement_id == req_id)
    )
    test_cases = tc_result.scalars().all()

    return {
        "requirement_id": req_id,
        "refined_requirement": (
            RefinedRequirementSchema.model_validate(refined_req)
            if refined_req
            else None
        ),
        "acceptance_criteria": [
            AcceptanceCriteriaSchema.model_validate(a) for a in ac_rows
        ],
        "test_cases": [TestCaseSchema.model_validate(tc) for tc in test_cases],
    }
