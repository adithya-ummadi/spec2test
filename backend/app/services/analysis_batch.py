"""Batch analysis runner — analyze all RAW requirements for a document.

Public API
----------
run_batch_analysis(db, document_id) -> BatchResult
    Analyze every RAW requirement belonging to *document_id* sequentially,
    persist findings, and update requirement statuses.

    The caller is responsible for committing (or rolling back) the session.
    If one requirement fails, the failure is logged and the loop continues so
    that already-successful results are preserved.

Design notes
------------
- Analysis failures do NOT update the requirement status; the row stays at
  "RAW" so that a retry is possible without manual intervention.
- The function does NOT commit the session — consistent with the existing
  service layer contract (see document_service.process_upload).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import FindingModel, RequirementModel
from app.services.analyzer import AnalysisError, analyze_requirement

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class BatchResult:
    """Summary of a completed batch analysis run."""

    analyzed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_batch_analysis(
    db: AsyncSession,
    document_id: int,
) -> BatchResult:
    """Analyze all RAW requirements for *document_id* and persist the results.

    Parameters
    ----------
    db:
        An active async SQLAlchemy session.  The caller must commit after this
        function returns.
    document_id:
        The ID of the document whose requirements should be analyzed.

    Returns
    -------
    BatchResult
        Counts of analyzed, failed, and skipped requirements plus any error
        messages collected during the run.
    """
    # Load all RAW requirements for the document in insertion order.
    stmt = (
        select(RequirementModel)
        .where(
            RequirementModel.document_id == document_id,
            RequirementModel.status == "RAW",
        )
        .order_by(RequirementModel.id)
    )
    result = await db.execute(stmt)
    requirements: Sequence[RequirementModel] = result.scalars().all()

    if not requirements:
        log.info(
            "No RAW requirements found for document %d — nothing to analyze.",
            document_id,
        )
        return BatchResult()

    log.info(
        "Starting batch analysis for document %d: %d RAW requirement(s).",
        document_id,
        len(requirements),
    )

    summary = BatchResult()

    for req in requirements:
        try:
            findings: list[FindingModel] = await analyze_requirement(req)
        except AnalysisError as exc:
            # Record the failure but do NOT update the requirement status.
            # The requirement stays RAW so that a retry is possible.
            error_msg = f"Requirement {req.id}: {exc}"
            log.error(error_msg)
            summary.failed += 1
            summary.errors.append(error_msg)
            # Flush to make sure any partial state from the failing iteration
            # doesn't linger.  There should be none, but be explicit.
            await db.flush()
            continue

        # Persist findings and mark requirement as ANALYZED.
        for finding in findings:
            db.add(finding)

        req.status = "ANALYZED"
        await db.flush()

        summary.analyzed += 1
        log.info(
            "Requirement %d analyzed successfully: %d finding(s).",
            req.id,
            len(findings),
        )

    log.info(
        "Batch analysis complete for document %d — analyzed: %d, failed: %d, skipped: %d.",
        document_id,
        summary.analyzed,
        summary.failed,
        summary.skipped,
    )
    return summary
