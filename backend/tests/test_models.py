"""Minimal tests to verify the data models can be imported and the database
can be initialised without errors.  No LLM, no document parsing."""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

# Use an in-memory SQLite database so tests leave no files on disk.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def test_enums_importable() -> None:
    from app.models.schemas import ConfidenceLevel, FindingType, RequirementStatus

    assert FindingType.AMBIGUITY == "AMBIGUITY"
    assert FindingType.MISSING_INFORMATION == "MISSING_INFORMATION"
    assert FindingType.CONTRADICTION == "CONTRADICTION"
    assert FindingType.TESTABILITY == "TESTABILITY"

    assert ConfidenceLevel.CONFIRMED == "CONFIRMED"
    assert ConfidenceLevel.LIKELY == "LIKELY"
    assert ConfidenceLevel.POSSIBLE == "POSSIBLE"
    assert ConfidenceLevel.INFORMATIONAL == "INFORMATIONAL"

    assert RequirementStatus.RAW == "RAW"
    assert RequirementStatus.ANALYZED == "ANALYZED"
    assert RequirementStatus.CLARIFIED == "CLARIFIED"
    assert RequirementStatus.REFINED == "REFINED"


def test_pydantic_models_importable() -> None:
    from app.models.schemas import (
        AcceptanceCriteriaSchema,
        DocumentUploadResponse,
        FindingSchema,
        RefinedRequirementSchema,
        RequirementSchema,
        TestCaseSchema,
        TraceabilityEntry,
    )

    # Verify each model can be instantiated with minimal data.
    doc = DocumentUploadResponse(id=1, filename="test.txt", status="PENDING", requirement_count=0)
    assert doc.id == 1

    req = RequirementSchema(
        id=1, document_id=1, text="The system shall do X.", status="RAW"
    )
    assert req.status == "RAW"

    finding = FindingSchema(
        id=1,
        requirement_id=1,
        type="AMBIGUITY",
        confidence="LIKELY",
    )
    assert finding.type == "AMBIGUITY"

    refined = RefinedRequirementSchema(id=1, requirement_id=1, text="The system shall do X clearly.")
    assert refined.requirement_id == 1

    ac = AcceptanceCriteriaSchema(id=1, requirement_id=1, criteria=["Given X, when Y, then Z."])
    assert len(ac.criteria) == 1

    tc = TestCaseSchema(
        id=1,
        requirement_id=1,
        title="Positive test for X",
        classification="positive",
    )
    assert tc.classification == "positive"

    entry = TraceabilityEntry(
        requirement_id=1,
        finding_ids=[1],
        refined_requirement_id=1,
        acceptance_criteria_ids=[1],
        test_case_ids=[1],
    )
    assert entry.requirement_id == 1


def test_orm_models_importable() -> None:
    from app.models.db import (
        AcceptanceCriteriaModel,
        Base,
        DocumentModel,
        FindingModel,
        RefinedRequirementModel,
        RequirementModel,
        TestCaseModel,
    )

    # All tables should be registered on the shared metadata.
    table_names = set(Base.metadata.tables.keys())
    assert "documents" in table_names
    assert "requirements" in table_names
    assert "findings" in table_names
    assert "refined_requirements" in table_names
    assert "acceptance_criteria" in table_names
    assert "test_cases" in table_names


@pytest.mark.asyncio
async def test_db_init_creates_tables() -> None:
    """init_db() must run without error and all tables must exist afterward."""
    from app.database import engine, init_db
    from app.models.db import Base

    await init_db()

    async with engine.connect() as conn:
        table_names = await conn.run_sync(
            lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
        )

    expected = {
        "documents",
        "requirements",
        "findings",
        "refined_requirements",
        "acceptance_criteria",
        "test_cases",
    }
    assert expected.issubset(set(table_names))


@pytest.mark.asyncio
async def test_db_crud_basic() -> None:
    """Insert a document and a requirement; verify the relationship is readable."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy import select

    from app.models.db import Base, DocumentModel, RequirementModel

    # Use a fresh in-memory engine so this test is fully isolated.
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSession() as session:
        doc = DocumentModel(filename="spec.txt", status="PENDING")
        session.add(doc)
        await session.flush()

        req = RequirementModel(
            document_id=doc.id,
            text="The system shall process uploads.",
            status="RAW",
        )
        session.add(req)
        await session.commit()

    async with TestSession() as session:
        result = await session.execute(select(RequirementModel))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].text == "The system shall process uploads."
        assert rows[0].status == "RAW"

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_acceptance_criteria_json_roundtrip() -> None:
    """criteria property serialises / deserialises correctly via JSON."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy import select

    from app.models.db import (
        AcceptanceCriteriaModel,
        Base,
        DocumentModel,
        RequirementModel,
    )

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSession() as session:
        doc = DocumentModel(filename="spec.txt", status="PENDING")
        session.add(doc)
        await session.flush()

        req = RequirementModel(document_id=doc.id, text="Req text", status="RAW")
        session.add(req)
        await session.flush()

        ac = AcceptanceCriteriaModel(requirement_id=req.id)
        ac.criteria = ["Given A, when B, then C.", "Given D, when E, then F."]
        session.add(ac)
        await session.commit()

    async with TestSession() as session:
        result = await session.execute(select(AcceptanceCriteriaModel))
        rows = result.scalars().all()
        assert rows[0].criteria == ["Given A, when B, then C.", "Given D, when E, then F."]

    await test_engine.dispose()
