"""API integration tests for Sub-Task 6 — REST API Layer.

All tests use an in-memory SQLite database and mock LLM calls.
No real OpenAI/API key is required.

Coverage:
- POST /api/documents/upload     (success, unsupported type)
- GET  /api/documents            (list)
- GET  /api/documents/{id}       (detail, 404)
- GET  /api/documents/{id}/requirements
- POST /api/documents/{id}/analyze
- GET  /api/documents/{id}/traceability
- GET  /api/requirements/{id}    (detail, 404)
- POST /api/requirements/{id}/analyze
- POST /api/requirements/{id}/refine
- GET  /api/requirements/{id}/refined
"""

from __future__ import annotations

import io
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Environment setup — must happen before any app imports
# ---------------------------------------------------------------------------

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

# ---------------------------------------------------------------------------
# App + DB wiring
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.models.db import Base
from app.main import app


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    SessionLocal = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    """AsyncClient wired to the FastAPI app with the in-memory DB session."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Mock LLM responses
# ---------------------------------------------------------------------------

_ANALYSIS_RESPONSE = {
    "findings": [
        {
            "type": "AMBIGUITY",
            "confidence": "LIKELY",
            "evidence": "The requirement is vague.",
        }
    ]
}

_REFINEMENT_RESPONSE = {
    "refined_requirement": "The system shall respond to all requests within 200 ms.",
    "acceptance_criteria": [
        "Given a valid request, when submitted, then respond within 200 ms.",
        "System shall log each request.",
    ],
    "test_cases": [
        {
            "title": "Happy path",
            "preconditions": "Service is running.",
            "steps": "1. Send request.",
            "expected_result": "Response in ≤200 ms.",
            "classification": "positive",
        },
        {
            "title": "Invalid input",
            "expected_result": "HTTP 400 returned.",
            "classification": "negative",
        },
        {
            "title": "Boundary value",
            "expected_result": "Exactly at 200 ms boundary.",
            "classification": "edge",
        },
    ],
}

ANALYZER_PATCH = "app.services.analyzer.llm_client.complete"
REFINER_PATCH = "app.services.refiner.llm_client.complete"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txt_file(content: str = "The system shall do X.\nThe system must do Y.\n") -> tuple:
    """Return (filename, file_bytes, content_type) for a fake TXT upload."""
    return ("spec.txt", content.encode(), "text/plain")


def _make_upload_files(filename: str, content: bytes, content_type: str):
    return {"file": (filename, io.BytesIO(content), content_type)}


# ---------------------------------------------------------------------------
# POST /api/documents/upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUploadDocument:
    async def test_upload_txt_success(self, client: AsyncClient):
        filename, content, ct = _txt_file()
        resp = await client.post(
            "/api/documents/upload",
            files=_make_upload_files(filename, content, ct),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "spec.txt"
        assert data["status"] == "PROCESSED"
        assert data["requirement_count"] >= 1
        assert "id" in data

    async def test_upload_markdown_success(self, client: AsyncClient):
        md = b"# Spec\n\nThe system shall handle uploads.\n"
        resp = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.md", md, "text/markdown"),
        )
        assert resp.status_code == 201
        assert resp.json()["filename"] == "spec.md"

    async def test_upload_unsupported_type_returns_415(self, client: AsyncClient):
        resp = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("photo.jpg", b"\xff\xd8\xff", "image/jpeg"),
        )
        assert resp.status_code == 415

    async def test_upload_returns_requirement_count(self, client: AsyncClient):
        content = (
            b"1. The system shall authenticate users.\n"
            b"2. The system shall log events.\n"
            b"3. Passwords must be hashed.\n"
        )
        resp = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        assert resp.status_code == 201
        assert resp.json()["requirement_count"] == 3

    async def test_upload_docx_success(self, client: AsyncClient):
        """A DOCX file with requirements is accepted."""
        import docx as python_docx

        doc = python_docx.Document()
        doc.add_paragraph("The system shall process DOCX files.")
        buf = io.BytesIO()
        doc.save(buf)
        docx_bytes = buf.getvalue()

        resp = await client.post(
            "/api/documents/upload",
            files=_make_upload_files(
                "spec.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListDocuments:
    async def test_empty_list_initially(self, client: AsyncClient):
        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_after_upload(self, client: AsyncClient):
        filename, content, ct = _txt_file()
        await client.post(
            "/api/documents/upload",
            files=_make_upload_files(filename, content, ct),
        )
        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 1
        assert docs[0]["filename"] == "spec.txt"

    async def test_list_contains_requirement_count(self, client: AsyncClient):
        content = b"1. Req A.\n2. Req B.\n"
        await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        resp = await client.get("/api/documents")
        docs = resp.json()
        assert docs[0]["requirement_count"] >= 1


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetDocument:
    async def test_get_existing_document(self, client: AsyncClient):
        filename, content, ct = _txt_file()
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files(filename, content, ct),
        )
        doc_id = upload.json()["id"]

        resp = await client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == doc_id

    async def test_get_unknown_document_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/documents/9999")
        assert resp.status_code == 404

    async def test_get_document_includes_status(self, client: AsyncClient):
        filename, content, ct = _txt_file()
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files(filename, content, ct),
        )
        doc_id = upload.json()["id"]
        resp = await client.get(f"/api/documents/{doc_id}")
        assert "status" in resp.json()


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/requirements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListDocumentRequirements:
    async def test_requirements_returned_after_upload(self, client: AsyncClient):
        content = b"1. The system shall do X.\n2. The system must do Y.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]

        resp = await client.get(f"/api/documents/{doc_id}/requirements")
        assert resp.status_code == 200
        reqs = resp.json()
        assert len(reqs) == 2
        for r in reqs:
            assert r["document_id"] == doc_id
            assert r["status"] == "RAW"

    async def test_requirements_for_unknown_document_returns_404(
        self, client: AsyncClient
    ):
        resp = await client.get("/api/documents/9999/requirements")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/documents/{doc_id}/analyze
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAnalyzeDocument:
    async def test_batch_analyze_returns_counts(self, client: AsyncClient):
        content = b"1. The system shall do X.\n2. The system must do Y.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]

        with patch(ANALYZER_PATCH, return_value=_ANALYSIS_RESPONSE):
            resp = await client.post(f"/api/documents/{doc_id}/analyze")

        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == doc_id
        assert data["analyzed"] == 2
        assert data["failed"] == 0

    async def test_analyze_unknown_document_returns_404(self, client: AsyncClient):
        resp = await client.post("/api/documents/9999/analyze")
        assert resp.status_code == 404

    async def test_requirements_status_becomes_analyzed(self, client: AsyncClient):
        content = b"The system shall log events.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]

        with patch(ANALYZER_PATCH, return_value=_ANALYSIS_RESPONSE):
            await client.post(f"/api/documents/{doc_id}/analyze")

        reqs_resp = await client.get(f"/api/documents/{doc_id}/requirements")
        statuses = [r["status"] for r in reqs_resp.json()]
        assert all(s == "ANALYZED" for s in statuses)


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/traceability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTraceability:
    async def test_traceability_for_unknown_document_returns_404(
        self, client: AsyncClient
    ):
        resp = await client.get("/api/documents/9999/traceability")
        assert resp.status_code == 404

    async def test_traceability_returns_entries_per_requirement(
        self, client: AsyncClient
    ):
        content = b"1. Req A.\n2. Req B.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]

        resp = await client.get(f"/api/documents/{doc_id}/traceability")
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 2
        for e in entries:
            assert "requirement_id" in e
            assert "finding_ids" in e
            assert "test_case_ids" in e

    async def test_traceability_after_refinement(self, client: AsyncClient):
        content = b"The system shall process requests.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs_resp = await client.get(f"/api/documents/{doc_id}/requirements")
        req_id = reqs_resp.json()[0]["id"]

        with patch(ANALYZER_PATCH, return_value=_ANALYSIS_RESPONSE):
            await client.post(f"/api/requirements/{req_id}/analyze")

        with patch(REFINER_PATCH, return_value=_REFINEMENT_RESPONSE):
            await client.post(f"/api/requirements/{req_id}/refine")

        resp = await client.get(f"/api/documents/{doc_id}/traceability")
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["refined_requirement_id"] is not None
        assert len(entry["finding_ids"]) == 1
        assert len(entry["test_case_ids"]) == 3


# ---------------------------------------------------------------------------
# GET /api/requirements/{req_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetRequirement:
    async def test_get_requirement_detail(self, client: AsyncClient):
        content = b"The system shall do X.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs = (await client.get(f"/api/documents/{doc_id}/requirements")).json()
        req_id = reqs[0]["id"]

        resp = await client.get(f"/api/requirements/{req_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["requirement"]["id"] == req_id
        assert "findings" in data

    async def test_get_unknown_requirement_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/requirements/9999")
        assert resp.status_code == 404

    async def test_get_requirement_includes_findings_after_analysis(
        self, client: AsyncClient
    ):
        content = b"The system shall do X.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs = (await client.get(f"/api/documents/{doc_id}/requirements")).json()
        req_id = reqs[0]["id"]

        with patch(ANALYZER_PATCH, return_value=_ANALYSIS_RESPONSE):
            await client.post(f"/api/requirements/{req_id}/analyze")

        resp = await client.get(f"/api/requirements/{req_id}")
        assert resp.status_code == 200
        assert len(resp.json()["findings"]) == 1


# ---------------------------------------------------------------------------
# POST /api/requirements/{req_id}/analyze
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAnalyzeSingleRequirement:
    async def test_analyze_returns_findings(self, client: AsyncClient):
        content = b"The system shall process requests.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs = (await client.get(f"/api/documents/{doc_id}/requirements")).json()
        req_id = reqs[0]["id"]

        with patch(ANALYZER_PATCH, return_value=_ANALYSIS_RESPONSE):
            resp = await client.post(f"/api/requirements/{req_id}/analyze")

        assert resp.status_code == 200
        data = resp.json()
        assert data["requirement_id"] == req_id
        assert data["status"] == "ANALYZED"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["type"] == "AMBIGUITY"

    async def test_analyze_unknown_requirement_returns_404(self, client: AsyncClient):
        resp = await client.post("/api/requirements/9999/analyze")
        assert resp.status_code == 404

    async def test_analyze_llm_failure_returns_error(self, client: AsyncClient):
        from app.services.llm_client import LLMError

        content = b"The system shall do X.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs = (await client.get(f"/api/documents/{doc_id}/requirements")).json()
        req_id = reqs[0]["id"]

        with patch(ANALYZER_PATCH, side_effect=LLMError("API down")):
            resp = await client.post(f"/api/requirements/{req_id}/analyze")

        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /api/requirements/{req_id}/refine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRefineRequirement:
    async def _upload_and_get_req_id(self, client: AsyncClient) -> tuple[int, int]:
        content = b"The system shall respond quickly.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs = (await client.get(f"/api/documents/{doc_id}/requirements")).json()
        return doc_id, reqs[0]["id"]

    async def test_refine_returns_all_artifacts(self, client: AsyncClient):
        _, req_id = await self._upload_and_get_req_id(client)

        with patch(ANALYZER_PATCH, return_value=_ANALYSIS_RESPONSE):
            await client.post(f"/api/requirements/{req_id}/analyze")

        with patch(REFINER_PATCH, return_value=_REFINEMENT_RESPONSE):
            resp = await client.post(f"/api/requirements/{req_id}/refine")

        assert resp.status_code == 200
        data = resp.json()
        assert data["requirement_id"] == req_id
        assert data["status"] == "REFINED"
        assert data["refined_requirement"]["text"] is not None
        assert len(data["acceptance_criteria"]["criteria"]) >= 1
        assert len(data["test_cases"]) == 3

    async def test_refine_unknown_requirement_returns_404(self, client: AsyncClient):
        with patch(REFINER_PATCH, return_value=_REFINEMENT_RESPONSE):
            resp = await client.post("/api/requirements/9999/refine")
        assert resp.status_code == 404

    async def test_refine_llm_failure_returns_error(self, client: AsyncClient):
        from app.services.llm_client import LLMError

        _, req_id = await self._upload_and_get_req_id(client)

        with patch(REFINER_PATCH, side_effect=LLMError("API down")):
            resp = await client.post(f"/api/requirements/{req_id}/refine")

        assert resp.status_code == 502

    async def test_refine_test_case_classifications(self, client: AsyncClient):
        _, req_id = await self._upload_and_get_req_id(client)

        with patch(REFINER_PATCH, return_value=_REFINEMENT_RESPONSE):
            resp = await client.post(f"/api/requirements/{req_id}/refine")

        data = resp.json()
        classifications = {tc["classification"] for tc in data["test_cases"]}
        assert "positive" in classifications
        assert "negative" in classifications
        assert "edge" in classifications


# ---------------------------------------------------------------------------
# GET /api/requirements/{req_id}/refined
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetRefined:
    async def _upload_analyze_refine(self, client: AsyncClient) -> tuple[int, int]:
        content = b"The system shall respond quickly.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs = (await client.get(f"/api/documents/{doc_id}/requirements")).json()
        req_id = reqs[0]["id"]

        with patch(ANALYZER_PATCH, return_value=_ANALYSIS_RESPONSE):
            await client.post(f"/api/requirements/{req_id}/analyze")

        with patch(REFINER_PATCH, return_value=_REFINEMENT_RESPONSE):
            await client.post(f"/api/requirements/{req_id}/refine")

        return doc_id, req_id

    async def test_refined_returns_full_data(self, client: AsyncClient):
        _, req_id = await self._upload_analyze_refine(client)

        resp = await client.get(f"/api/requirements/{req_id}/refined")
        assert resp.status_code == 200
        data = resp.json()
        assert data["requirement_id"] == req_id
        assert data["refined_requirement"] is not None
        assert len(data["acceptance_criteria"]) == 1
        assert len(data["test_cases"]) == 3

    async def test_refined_unknown_requirement_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/requirements/9999/refined")
        assert resp.status_code == 404

    async def test_refined_before_refinement_returns_nulls(self, client: AsyncClient):
        content = b"The system shall do X.\n"
        upload = await client.post(
            "/api/documents/upload",
            files=_make_upload_files("spec.txt", content, "text/plain"),
        )
        doc_id = upload.json()["id"]
        reqs = (await client.get(f"/api/documents/{doc_id}/requirements")).json()
        req_id = reqs[0]["id"]

        resp = await client.get(f"/api/requirements/{req_id}/refined")
        assert resp.status_code == 200
        data = resp.json()
        assert data["refined_requirement"] is None
        assert data["acceptance_criteria"] == []
        assert data["test_cases"] == []
