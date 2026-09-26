"""SQLAlchemy ORM models for Spec2Test."""

from __future__ import annotations

import json

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, server_default=func.now())

    requirements = relationship(
        "RequirementModel", back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def requirement_count(self) -> int:
        return len(self.requirements)


# ---------------------------------------------------------------------------
# Requirement
# ---------------------------------------------------------------------------


class RequirementModel(Base):
    __tablename__ = "requirements"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    source_location = Column(String, nullable=True)
    status = Column(String, default="RAW")  # RequirementStatus

    document = relationship("DocumentModel", back_populates="requirements")
    findings = relationship(
        "FindingModel", back_populates="requirement", cascade="all, delete-orphan"
    )
    refined_requirement = relationship(
        "RefinedRequirementModel",
        back_populates="requirement",
        uselist=False,
        cascade="all, delete-orphan",
    )
    acceptance_criteria = relationship(
        "AcceptanceCriteriaModel", back_populates="requirement", cascade="all, delete-orphan"
    )
    test_cases = relationship(
        "TestCaseModel", back_populates="requirement", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class FindingModel(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, index=True)
    requirement_id = Column(Integer, ForeignKey("requirements.id"), nullable=False, index=True)
    type = Column(String, nullable=False)         # FindingType
    confidence = Column(String, nullable=False)   # ConfidenceLevel
    evidence = Column(Text, nullable=True)
    missing_info = Column(Text, nullable=True)
    suggested_clarification = Column(Text, nullable=True)

    requirement = relationship("RequirementModel", back_populates="findings")


# ---------------------------------------------------------------------------
# Refined Requirement
# ---------------------------------------------------------------------------


class RefinedRequirementModel(Base):
    __tablename__ = "refined_requirements"

    id = Column(Integer, primary_key=True, index=True)
    requirement_id = Column(
        Integer, ForeignKey("requirements.id"), nullable=False, unique=True, index=True
    )
    text = Column(Text, nullable=False)

    requirement = relationship(
        "RequirementModel", back_populates="refined_requirement"
    )


# ---------------------------------------------------------------------------
# Acceptance Criteria
# ---------------------------------------------------------------------------


class AcceptanceCriteriaModel(Base):
    __tablename__ = "acceptance_criteria"

    id = Column(Integer, primary_key=True, index=True)
    requirement_id = Column(Integer, ForeignKey("requirements.id"), nullable=False, index=True)
    # Stored as a JSON-serialised list of strings for SQLite compatibility.
    criteria_json = Column(Text, nullable=False, default="[]")

    requirement = relationship(
        "RequirementModel", back_populates="acceptance_criteria"
    )

    # Convenience property so the rest of the code can work with a plain list.
    @property
    def criteria(self) -> list:
        return json.loads(self.criteria_json)

    @criteria.setter
    def criteria(self, value: list) -> None:
        self.criteria_json = json.dumps(value)


# ---------------------------------------------------------------------------
# Test Case
# ---------------------------------------------------------------------------


class TestCaseModel(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, index=True)
    requirement_id = Column(Integer, ForeignKey("requirements.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    preconditions = Column(Text, nullable=True)
    steps = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)
    classification = Column(String, nullable=True)  # positive / negative / edge

    requirement = relationship("RequirementModel", back_populates="test_cases")
