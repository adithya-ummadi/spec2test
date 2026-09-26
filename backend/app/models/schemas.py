"""Pydantic schemas for Spec2Test — the canonical request/response shapes."""

from __future__ import annotations

import enum
from typing import List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FindingType(str, enum.Enum):
    AMBIGUITY = "AMBIGUITY"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    CONTRADICTION = "CONTRADICTION"
    TESTABILITY = "TESTABILITY"


class ConfidenceLevel(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    LIKELY = "LIKELY"
    POSSIBLE = "POSSIBLE"
    INFORMATIONAL = "INFORMATIONAL"


class RequirementStatus(str, enum.Enum):
    RAW = "RAW"
    ANALYZED = "ANALYZED"
    CLARIFIED = "CLARIFIED"
    REFINED = "REFINED"


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class DocumentUploadResponse(BaseModel):
    id: int
    filename: str
    status: str
    requirement_count: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Requirement
# ---------------------------------------------------------------------------


class RequirementSchema(BaseModel):
    id: int
    document_id: int
    text: str
    source_location: Optional[str] = None
    status: RequirementStatus

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class FindingSchema(BaseModel):
    id: int
    requirement_id: int
    type: FindingType
    confidence: ConfidenceLevel
    evidence: Optional[str] = None
    missing_info: Optional[str] = None
    suggested_clarification: Optional[str] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Refined Requirement
# ---------------------------------------------------------------------------


class RefinedRequirementSchema(BaseModel):
    id: int
    requirement_id: int
    text: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Acceptance Criteria
# ---------------------------------------------------------------------------


class AcceptanceCriteriaSchema(BaseModel):
    id: int
    requirement_id: int
    criteria: List[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Test Case
# ---------------------------------------------------------------------------


class TestCaseSchema(BaseModel):
    id: int
    requirement_id: int
    title: str
    preconditions: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    classification: Optional[str] = None  # positive / negative / edge

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


class TraceabilityEntry(BaseModel):
    requirement_id: int
    finding_ids: List[int]
    refined_requirement_id: Optional[int] = None
    acceptance_criteria_ids: List[int]
    test_case_ids: List[int]
