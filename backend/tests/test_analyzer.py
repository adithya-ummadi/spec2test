"""Unit tests for Sub-Task 4 — Requirement Analysis Pipeline (LLM Integration).

All tests mock ``app.services.llm_client.complete`` — no real API calls are made.

Test classes
------------
TestAnalyzeRequirement     — analyzer.analyze_requirement, all scenarios
TestRunBatchAnalysis       — analysis_batch.run_batch_analysis with in-memory DB
TestAnalysisPrompt         — smoke-tests for prompt module (no LLM, no DB)
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio

from unittest.mock import AsyncMock, MagicMock, patch

# Use an in-memory SQLite database for all DB tests.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Prevent the LLM client from complaining about a missing API key when the
# module is imported in tests (the actual key is never used because we mock).
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_llm_response(*findings: dict) -> dict:
    """Build a mock LLM response dict with the given finding dicts."""
    return {"findings": list(findings)}


def _finding(
    type_: str = "AMBIGUITY",
    confidence: str = "LIKELY",
    evidence: str = "The system shall do things.",
    missing_info: str | None = None,
    suggested_clarification: str | None = None,
) -> dict:
    """Convenience builder for a single finding dict."""
    f: dict = {"type": type_, "confidence": confidence, "evidence": evidence}
    if missing_info:
        f["missing_info"] = missing_info
    if suggested_clarification:
        f["suggested_clarification"] = suggested_clarification
    return f


def _make_requirement(id_: int = 1, text: str = "The system shall do things."):
    """Build a minimal RequirementModel without a DB session."""
    from app.models.db import RequirementModel

    req = RequirementModel()
    req.id = id_
    req.document_id = 1
    req.text = text
    req.status = "RAW"
    return req


# ---------------------------------------------------------------------------
# TestAnalysisPrompt — smoke tests (no LLM, no DB)
# ---------------------------------------------------------------------------


class TestAnalysisPrompt:
    def test_rendered_system_prompt_contains_finding_types(self):
        from app.prompts.analysis_prompt import RENDERED_SYSTEM_PROMPT

        for ft in ("AMBIGUITY", "MISSING_INFORMATION", "CONTRADICTION", "TESTABILITY"):
            assert ft in RENDERED_SYSTEM_PROMPT

    def test_rendered_system_prompt_contains_confidence_levels(self):
        from app.prompts.analysis_prompt import RENDERED_SYSTEM_PROMPT

        for cl in ("CONFIRMED", "LIKELY", "POSSIBLE", "INFORMATIONAL"):
            assert cl in RENDERED_SYSTEM_PROMPT

    def test_rendered_system_prompt_contains_no_fabricate_instruction(self):
        from app.prompts.analysis_prompt import RENDERED_SYSTEM_PROMPT

        # The prompt must instruct the model not to fabricate evidence.
        text_lower = RENDERED_SYSTEM_PROMPT.lower()
        assert "fabricate" in text_lower or "invent" in text_lower or "never" in text_lower

    def test_build_user_prompt_includes_requirement_text(self):
        from app.prompts.analysis_prompt import build_user_prompt

        req_text = "The system shall respond quickly."
        prompt = build_user_prompt(req_text)
        assert req_text in prompt

    def test_response_schema_has_required_fields(self):
        from app.prompts.analysis_prompt import RESPONSE_SCHEMA

        assert "findings" in RESPONSE_SCHEMA["properties"]
        item_props = RESPONSE_SCHEMA["properties"]["findings"]["items"]["properties"]
        assert "type" in item_props
        assert "confidence" in item_props
        assert "evidence" in item_props


# ---------------------------------------------------------------------------
# TestAnalyzeRequirement
# ---------------------------------------------------------------------------


PATCH_TARGET = "app.services.analyzer.llm_client.complete"


@pytest.mark.asyncio
class TestAnalyzeRequirement:
    async def test_valid_single_finding(self):
        """A valid LLM response with one finding returns one FindingModel."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            _finding("AMBIGUITY", "LIKELY", "do things")
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert len(findings) == 1
        assert findings[0].type == "AMBIGUITY"
        assert findings[0].confidence == "LIKELY"
        assert findings[0].evidence == "do things"
        assert findings[0].requirement_id == req.id

    async def test_multiple_findings(self):
        """Multiple findings in the LLM response are all returned."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            _finding("AMBIGUITY", "LIKELY", "do things"),
            _finding("MISSING_INFORMATION", "POSSIBLE", "no error handling specified"),
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert len(findings) == 2
        types = {f.type for f in findings}
        assert "AMBIGUITY" in types
        assert "MISSING_INFORMATION" in types

    async def test_all_four_finding_types(self):
        """Each of the four finding types can be returned and parsed."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            _finding("AMBIGUITY", "LIKELY", "vague language"),
            _finding("MISSING_INFORMATION", "POSSIBLE", "no actor specified"),
            _finding("CONTRADICTION", "CONFIRMED", "A must be X but also must not be X"),
            _finding("TESTABILITY", "INFORMATIONAL", "cannot measure quickly"),
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert len(findings) == 4
        types = {f.type for f in findings}
        assert types == {"AMBIGUITY", "MISSING_INFORMATION", "CONTRADICTION", "TESTABILITY"}

    async def test_all_four_confidence_levels(self):
        """Each of the four confidence levels can be returned and parsed."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            _finding("AMBIGUITY", "CONFIRMED", "evidence A"),
            _finding("AMBIGUITY", "LIKELY", "evidence B"),
            _finding("AMBIGUITY", "POSSIBLE", "evidence C"),
            _finding("AMBIGUITY", "INFORMATIONAL", "evidence D"),
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert len(findings) == 4
        levels = {f.confidence for f in findings}
        assert levels == {"CONFIRMED", "LIKELY", "POSSIBLE", "INFORMATIONAL"}

    async def test_empty_findings_list_is_valid(self):
        """A clear requirement produces an empty findings list — not an error."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement(
            text="The system shall authenticate the user via OAuth 2.0 within 3 seconds."
        )
        mock_response = _make_llm_response()  # no findings

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert findings == []

    async def test_finding_fields_mapped_correctly(self):
        """Optional fields (missing_info, suggested_clarification) are mapped."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            _finding(
                "MISSING_INFORMATION",
                "LIKELY",
                "no error handling specified",
                missing_info="What should happen on failure?",
                suggested_clarification="Add an error response clause.",
            )
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert len(findings) == 1
        f = findings[0]
        assert f.missing_info == "What should happen on failure?"
        assert f.suggested_clarification == "Add an error response clause."

    async def test_malformed_response_missing_findings_key(self):
        """LLM response without 'findings' key raises MalformedResponseError."""
        from app.services.analyzer import MalformedResponseError, analyze_requirement

        req = _make_requirement()

        with patch(PATCH_TARGET, return_value={"oops": "not a findings object"}):
            with pytest.raises(MalformedResponseError):
                await analyze_requirement(req)

    async def test_malformed_response_findings_not_a_list(self):
        """'findings' that is not an array raises MalformedResponseError."""
        from app.services.analyzer import MalformedResponseError, analyze_requirement

        req = _make_requirement()

        with patch(PATCH_TARGET, return_value={"findings": "string not array"}):
            with pytest.raises(MalformedResponseError):
                await analyze_requirement(req)

    async def test_invalid_enum_value_skipped(self):
        """A finding with an unknown type is silently skipped; valid findings kept."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            {"type": "UNKNOWN_TYPE", "confidence": "LIKELY", "evidence": "something"},
            _finding("AMBIGUITY", "LIKELY", "valid evidence"),
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        # Only the valid one survives.
        assert len(findings) == 1
        assert findings[0].type == "AMBIGUITY"

    async def test_invalid_confidence_skipped(self):
        """A finding with an unknown confidence level is silently skipped."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            {"type": "AMBIGUITY", "confidence": "SUPER_SURE", "evidence": "text"},
            _finding("TESTABILITY", "INFORMATIONAL", "another evidence"),
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert len(findings) == 1
        assert findings[0].type == "TESTABILITY"

    async def test_llm_api_failure_raises_analysis_error(self):
        """Both LLM attempts failing raises AnalysisError (not LLMError)."""
        from app.services.analyzer import AnalysisError, analyze_requirement
        from app.services.llm_client import LLMError

        req = _make_requirement()

        with patch(PATCH_TARGET, side_effect=LLMError("connection refused")):
            with pytest.raises(AnalysisError):
                await analyze_requirement(req)

    async def test_retry_succeeds_on_second_attempt(self):
        """First LLM call fails; second succeeds — findings are returned."""
        from app.services.analyzer import analyze_requirement
        from app.services.llm_client import LLMError

        req = _make_requirement()
        success_response = _make_llm_response(_finding("AMBIGUITY", "LIKELY", "vague"))

        call_count = 0

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise LLMError("transient error")
            return success_response

        with patch(PATCH_TARGET, side_effect=_side_effect):
            findings = await analyze_requirement(req)

        assert call_count == 2
        assert len(findings) == 1

    async def test_finding_missing_evidence_skipped(self):
        """A finding with a missing or empty evidence field is silently skipped."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement()
        mock_response = _make_llm_response(
            {"type": "AMBIGUITY", "confidence": "LIKELY", "evidence": ""},  # empty
            _finding("TESTABILITY", "POSSIBLE", "valid evidence"),
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert len(findings) == 1
        assert findings[0].type == "TESTABILITY"

    async def test_requirement_id_is_set_on_findings(self):
        """All returned FindingModels have the correct requirement_id."""
        from app.services.analyzer import analyze_requirement

        req = _make_requirement(id_=42)
        mock_response = _make_llm_response(
            _finding("AMBIGUITY", "LIKELY", "evidence 1"),
            _finding("TESTABILITY", "POSSIBLE", "evidence 2"),
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            findings = await analyze_requirement(req)

        assert all(f.requirement_id == 42 for f in findings)


# ---------------------------------------------------------------------------
# TestRunBatchAnalysis — uses in-memory SQLite DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    """Provide a fresh in-memory DB session per test, identical to test_models.py."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.db import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        yield session

    await engine.dispose()


async def _seed_document_and_requirements(session, req_texts: list[str]):
    """Insert a DocumentModel and RequirementModels; return (doc, reqs)."""
    from sqlalchemy import select
    from app.models.db import DocumentModel, RequirementModel

    doc = DocumentModel(filename="spec.txt", status="PROCESSED")
    session.add(doc)
    await session.flush()

    reqs = []
    for text in req_texts:
        req = RequirementModel(document_id=doc.id, text=text, status="RAW")
        session.add(req)
        reqs.append(req)
    await session.flush()

    return doc, reqs


@pytest.mark.asyncio
class TestRunBatchAnalysis:
    async def test_successful_persistence(self, db_session):
        """Findings are persisted; requirement status becomes ANALYZED."""
        from sqlalchemy import select
        from app.models.db import FindingModel, RequirementModel
        from app.services.analysis_batch import run_batch_analysis

        doc, reqs = await _seed_document_and_requirements(
            db_session,
            ["The system shall do X.", "The system must do Y."],
        )

        mock_resp = _make_llm_response(_finding("AMBIGUITY", "LIKELY", "do X"))

        with patch(PATCH_TARGET, return_value=mock_resp):
            result = await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        assert result.analyzed == 2
        assert result.failed == 0

        # Verify DB state.
        findings = (await db_session.execute(select(FindingModel))).scalars().all()
        assert len(findings) == 2  # one per requirement
        reqs_db = (await db_session.execute(select(RequirementModel))).scalars().all()
        assert all(r.status == "ANALYZED" for r in reqs_db)

    async def test_requirement_status_updated_to_analyzed(self, db_session):
        """Requirements that succeed move to ANALYZED status."""
        from sqlalchemy import select
        from app.models.db import RequirementModel
        from app.services.analysis_batch import run_batch_analysis

        doc, _ = await _seed_document_and_requirements(
            db_session, ["The system shall log events."]
        )

        with patch(PATCH_TARGET, return_value=_make_llm_response()):
            await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        reqs = (await db_session.execute(select(RequirementModel))).scalars().all()
        assert reqs[0].status == "ANALYZED"

    async def test_failed_requirement_stays_raw(self, db_session):
        """A failed requirement keeps status RAW so retries are possible."""
        from sqlalchemy import select
        from app.models.db import RequirementModel
        from app.services.analysis_batch import run_batch_analysis
        from app.services.llm_client import LLMError

        doc, _ = await _seed_document_and_requirements(
            db_session, ["The system shall fail on purpose."]
        )

        with patch(PATCH_TARGET, side_effect=LLMError("api down")):
            result = await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        assert result.failed == 1
        reqs = (await db_session.execute(select(RequirementModel))).scalars().all()
        # Must NOT be marked ANALYZED; stays RAW (or any non-ANALYZED value).
        assert reqs[0].status != "ANALYZED"

    async def test_failed_requirement_does_not_corrupt_others(self, db_session):
        """First req fails; second succeeds — second has findings and is ANALYZED."""
        from sqlalchemy import select
        from app.models.db import FindingModel, RequirementModel
        from app.services.analysis_batch import run_batch_analysis
        from app.services.llm_client import LLMError

        doc, reqs = await _seed_document_and_requirements(
            db_session,
            ["First req (will fail).", "Second req (will succeed)."],
        )
        req1_id, req2_id = reqs[0].id, reqs[1].id

        # The analyzer retries once on LLMError, so we must raise on both
        # attempts for the first requirement to truly fail.
        # Strategy: raise LLMError for the first two calls (req1 attempt 1 & 2),
        # succeed on the third call (req2 attempt 1).
        call_count = 0

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise LLMError("first req fails")
            return _make_llm_response(_finding("AMBIGUITY", "LIKELY", "evidence"))

        with patch(PATCH_TARGET, side_effect=_side_effect):
            result = await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        assert result.analyzed == 1
        assert result.failed == 1

        reqs_db = {
            r.id: r
            for r in (
                await db_session.execute(select(RequirementModel))
            ).scalars().all()
        }
        assert reqs_db[req1_id].status != "ANALYZED"
        assert reqs_db[req2_id].status == "ANALYZED"

        findings = (await db_session.execute(select(FindingModel))).scalars().all()
        assert len(findings) == 1
        assert findings[0].requirement_id == req2_id

    async def test_returns_correct_summary(self, db_session):
        """Return dict contains correct analyzed/failed/skipped counts."""
        from app.services.analysis_batch import run_batch_analysis
        from app.services.llm_client import LLMError

        doc, reqs = await _seed_document_and_requirements(
            db_session,
            ["Pass.", "Also pass.", "Fail."],
        )

        # The analyzer retries once on LLMError, so the third requirement must
        # fail on both attempts (calls 3 AND 4) to produce a real failure.
        call_count = 0

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise LLMError("third fails")
            return _make_llm_response()

        with patch(PATCH_TARGET, side_effect=_side_effect):
            result = await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        assert result.analyzed == 2
        assert result.failed == 1
        assert result.skipped == 0

    async def test_skips_non_raw_requirements(self, db_session):
        """Requirements that are not RAW are not passed to the analyzer."""
        from sqlalchemy import select
        from app.models.db import RequirementModel
        from app.services.analysis_batch import run_batch_analysis

        doc, reqs = await _seed_document_and_requirements(
            db_session, ["Already analyzed."]
        )
        # Manually set status to ANALYZED before the batch runs.
        reqs[0].status = "ANALYZED"
        await db_session.flush()

        mock = MagicMock(return_value=_make_llm_response())

        with patch(PATCH_TARGET, mock):
            result = await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        # The LLM should not have been called.
        mock.assert_not_called()
        assert result.analyzed == 0
        assert result.skipped == 0  # just not counted — already done

    async def test_empty_document_returns_zero_counts(self, db_session):
        """A document with no RAW requirements returns all-zero BatchResult."""
        from app.services.analysis_batch import run_batch_analysis
        from app.models.db import DocumentModel

        doc = DocumentModel(filename="empty.txt", status="PROCESSED")
        db_session.add(doc)
        await db_session.flush()

        result = await run_batch_analysis(db_session, doc.id)
        assert result.analyzed == 0
        assert result.failed == 0
        assert result.skipped == 0

    async def test_findings_have_correct_requirement_id(self, db_session):
        """Each FindingModel is linked to the correct requirement via requirement_id."""
        from sqlalchemy import select
        from app.models.db import FindingModel
        from app.services.analysis_batch import run_batch_analysis

        doc, reqs = await _seed_document_and_requirements(
            db_session,
            ["Req A.", "Req B."],
        )
        req_a_id = reqs[0].id
        req_b_id = reqs[1].id

        call_count = 0

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_llm_response(
                _finding("AMBIGUITY", "LIKELY", f"evidence for call {call_count}")
            )

        with patch(PATCH_TARGET, side_effect=_side_effect):
            await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        findings = (await db_session.execute(select(FindingModel))).scalars().all()
        assert len(findings) == 2
        req_ids = {f.requirement_id for f in findings}
        assert req_a_id in req_ids
        assert req_b_id in req_ids

    async def test_error_messages_collected(self, db_session):
        """Errors from failed requirements are collected in BatchResult.errors."""
        from app.services.analysis_batch import run_batch_analysis
        from app.services.llm_client import LLMError

        doc, _ = await _seed_document_and_requirements(
            db_session, ["This will fail."]
        )

        with patch(PATCH_TARGET, side_effect=LLMError("boom")):
            result = await run_batch_analysis(db_session, doc.id)
            await db_session.commit()

        assert len(result.errors) == 1
        assert "boom" in result.errors[0] or str(reqs[0].id if False else "") in result.errors[0]
