"""Unit tests for Sub-Task 5 — Clarification & Refinement Pipeline (LLM Integration).

All tests mock ``app.services.llm_client.complete`` — no real API calls are made.

Test classes
------------
TestRefinementPrompt        — smoke-tests for prompt module (no LLM, no DB)
TestParseResponse           — _parse_response internals in isolation (no LLM, no DB)
TestRefineRequirement       — refiner.refine_requirement with in-memory DB
TestTraceability            — verify ORM relationships form the correct chain
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio

from unittest.mock import MagicMock, patch

# Use an in-memory SQLite database for all DB tests.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Prevent the LLM client from complaining about a missing API key.
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_requirement(id_: int = 1, text: str = "The system shall respond quickly."):
    """Build a minimal RequirementModel without a DB session."""
    from app.models.db import RequirementModel

    req = RequirementModel()
    req.id = id_
    req.document_id = 1
    req.text = text
    req.status = "ANALYZED"
    return req


def _make_finding(
    id_: int = 1,
    requirement_id: int = 1,
    type_: str = "AMBIGUITY",
    confidence: str = "LIKELY",
    evidence: str = "respond quickly",
    missing_info: str | None = None,
    suggested_clarification: str | None = None,
):
    """Build a minimal FindingModel without a DB session."""
    from app.models.db import FindingModel

    f = FindingModel()
    f.id = id_
    f.requirement_id = requirement_id
    f.type = type_
    f.confidence = confidence
    f.evidence = evidence
    f.missing_info = missing_info
    f.suggested_clarification = suggested_clarification
    return f


def _valid_llm_response(
    refined_requirement: str = "The system shall respond to all API requests within 200 ms.",
    acceptance_criteria: list[str] | None = None,
    test_cases: list[dict] | None = None,
) -> dict:
    """Build a fully-valid mock LLM response dict."""
    if acceptance_criteria is None:
        acceptance_criteria = [
            "Given a valid API request, when the system receives it, then it shall respond within 200 ms.",
            "Given an invalid request, when processed, then the system shall return a 400 error within 200 ms.",
        ]
    if test_cases is None:
        test_cases = [
            {
                "title": "Valid request meets latency SLA",
                "preconditions": "API service is running and healthy.",
                "steps": "1. Send a well-formed GET request.\n2. Record response time.",
                "expected_result": "Response received in ≤200 ms with HTTP 200.",
                "classification": "positive",
            },
            {
                "title": "Invalid request returns error promptly",
                "preconditions": "API service is running.",
                "steps": "1. Send a malformed request body.\n2. Record response time.",
                "expected_result": "HTTP 400 returned in ≤200 ms.",
                "classification": "negative",
            },
            {
                "title": "Response at exact 200 ms boundary",
                "preconditions": "API service is running under simulated load.",
                "steps": "1. Send request timed to arrive at exactly 200 ms threshold.",
                "expected_result": "Response treated as within SLA.",
                "classification": "edge",
            },
        ]
    return {
        "refined_requirement": refined_requirement,
        "acceptance_criteria": acceptance_criteria,
        "test_cases": test_cases,
    }


# Patch target for the LLM client used by the refiner.
PATCH_TARGET = "app.services.refiner.llm_client.complete"


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    """Provide a fresh in-memory DB session per test."""
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


async def _seed_analyzed_requirement(session, text: str = "The system shall respond quickly."):
    """Insert Document + Requirement (ANALYZED) + two Findings; return (req, findings)."""
    from app.models.db import DocumentModel, FindingModel, RequirementModel

    doc = DocumentModel(filename="spec.txt", status="PROCESSED")
    session.add(doc)
    await session.flush()

    req = RequirementModel(document_id=doc.id, text=text, status="ANALYZED")
    session.add(req)
    await session.flush()

    f1 = FindingModel(
        requirement_id=req.id,
        type="AMBIGUITY",
        confidence="LIKELY",
        evidence="respond quickly",
        missing_info=None,
        suggested_clarification="Define a measurable time threshold.",
    )
    f2 = FindingModel(
        requirement_id=req.id,
        type="TESTABILITY",
        confidence="POSSIBLE",
        evidence="quickly",
        missing_info="No numeric threshold specified.",
        suggested_clarification=None,
    )
    session.add(f1)
    session.add(f2)
    await session.flush()

    return req, [f1, f2]


# ---------------------------------------------------------------------------
# TestRefinementPrompt — smoke tests (no LLM, no DB)
# ---------------------------------------------------------------------------


class TestRefinementPrompt:
    def test_rendered_system_prompt_contains_schema(self):
        from app.prompts.refinement_prompt import RENDERED_SYSTEM_PROMPT

        assert "refined_requirement" in RENDERED_SYSTEM_PROMPT
        assert "acceptance_criteria" in RENDERED_SYSTEM_PROMPT
        assert "test_cases" in RENDERED_SYSTEM_PROMPT

    def test_rendered_system_prompt_contains_classification_values(self):
        from app.prompts.refinement_prompt import RENDERED_SYSTEM_PROMPT

        for classification in ("positive", "negative", "edge"):
            assert classification in RENDERED_SYSTEM_PROMPT

    def test_rendered_system_prompt_instructs_no_fabrication(self):
        from app.prompts.refinement_prompt import RENDERED_SYSTEM_PROMPT

        text_lower = RENDERED_SYSTEM_PROMPT.lower()
        assert (
            "invent" in text_lower
            or "fabricate" in text_lower
            or "not supported" in text_lower
        ), "Prompt must instruct the model not to invent unsupported facts."

    def test_rendered_system_prompt_mentions_given_when_then(self):
        from app.prompts.refinement_prompt import RENDERED_SYSTEM_PROMPT

        assert "Given/When/Then" in RENDERED_SYSTEM_PROMPT or "given/when/then" in RENDERED_SYSTEM_PROMPT.lower()

    def test_response_schema_has_all_required_keys(self):
        from app.prompts.refinement_prompt import RESPONSE_SCHEMA

        required = RESPONSE_SCHEMA.get("required", [])
        assert "refined_requirement" in required
        assert "acceptance_criteria" in required
        assert "test_cases" in required

    def test_response_schema_test_case_has_classification_enum(self):
        from app.prompts.refinement_prompt import RESPONSE_SCHEMA

        tc_props = RESPONSE_SCHEMA["properties"]["test_cases"]["items"]["properties"]
        assert "classification" in tc_props
        assert set(tc_props["classification"]["enum"]) == {"positive", "negative", "edge"}

    def test_build_user_prompt_includes_requirement_text(self):
        from app.prompts.refinement_prompt import build_user_prompt

        req_text = "The system shall store user data."
        prompt = build_user_prompt(req_text, [])
        assert req_text in prompt

    def test_build_user_prompt_with_no_findings_has_no_findings_message(self):
        from app.prompts.refinement_prompt import build_user_prompt

        prompt = build_user_prompt("Req text.", [])
        assert "None" in prompt or "no identified defects" in prompt.lower()

    def test_build_user_prompt_includes_finding_type_and_evidence(self):
        from app.prompts.refinement_prompt import build_user_prompt

        finding = _make_finding(evidence="respond quickly", type_="AMBIGUITY")
        prompt = build_user_prompt("The system shall respond quickly.", [finding])
        assert "AMBIGUITY" in prompt
        assert "respond quickly" in prompt

    def test_build_user_prompt_includes_missing_info_when_present(self):
        from app.prompts.refinement_prompt import build_user_prompt

        finding = _make_finding(
            missing_info="No threshold defined.",
            suggested_clarification="Add a numeric value.",
        )
        prompt = build_user_prompt("Req.", [finding])
        assert "No threshold defined." in prompt
        assert "Add a numeric value." in prompt


# ---------------------------------------------------------------------------
# TestParseResponse — _parse_response internals
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for the internal _parse_response helper (imported directly)."""

    def _parse(self, raw: dict, requirement_id: int = 1):
        from app.services.refiner import _parse_response
        return _parse_response(raw, requirement_id)

    def test_valid_response_returns_three_objects(self):
        refined_req, ac, test_cases = self._parse(_valid_llm_response())
        assert refined_req is not None
        assert ac is not None
        assert len(test_cases) >= 1

    def test_refined_requirement_text_is_set(self):
        refined_req, _, _ = self._parse(_valid_llm_response(
            refined_requirement="System shall respond within 200 ms."
        ))
        assert refined_req.text == "System shall respond within 200 ms."

    def test_refined_requirement_has_correct_requirement_id(self):
        refined_req, _, _ = self._parse(_valid_llm_response(), requirement_id=42)
        assert refined_req.requirement_id == 42

    def test_acceptance_criteria_stored_correctly(self):
        criteria = ["Given X, when Y, then Z.", "The system shall log the event."]
        _, ac, _ = self._parse(_valid_llm_response(acceptance_criteria=criteria))
        assert ac.criteria == criteria

    def test_acceptance_criteria_has_correct_requirement_id(self):
        _, ac, _ = self._parse(_valid_llm_response(), requirement_id=7)
        assert ac.requirement_id == 7

    def test_positive_test_case_parsed(self):
        _, _, test_cases = self._parse(_valid_llm_response(test_cases=[
            {
                "title": "Happy path",
                "expected_result": "System responds correctly.",
                "classification": "positive",
            }
        ]))
        assert len(test_cases) == 1
        assert test_cases[0].classification == "positive"
        assert test_cases[0].title == "Happy path"

    def test_negative_test_case_parsed(self):
        _, _, test_cases = self._parse(_valid_llm_response(test_cases=[
            {
                "title": "Invalid input",
                "expected_result": "System returns 400.",
                "classification": "negative",
            }
        ]))
        assert test_cases[0].classification == "negative"

    def test_edge_test_case_parsed(self):
        _, _, test_cases = self._parse(_valid_llm_response(test_cases=[
            {
                "title": "Boundary value",
                "expected_result": "System handles boundary correctly.",
                "classification": "edge",
            }
        ]))
        assert test_cases[0].classification == "edge"

    def test_all_three_classifications_in_response(self):
        response = _valid_llm_response()
        _, _, test_cases = self._parse(response)
        classifications = {tc.classification for tc in test_cases}
        assert "positive" in classifications
        assert "negative" in classifications
        assert "edge" in classifications

    def test_test_case_optional_fields_set(self):
        _, _, test_cases = self._parse(_valid_llm_response(test_cases=[
            {
                "title": "Full test",
                "preconditions": "System is running.",
                "steps": "1. Do this.\n2. Do that.",
                "expected_result": "Success.",
                "classification": "positive",
            }
        ]))
        tc = test_cases[0]
        assert tc.preconditions == "System is running."
        assert tc.steps == "1. Do this.\n2. Do that."

    def test_test_case_optional_fields_absent(self):
        _, _, test_cases = self._parse(_valid_llm_response(test_cases=[
            {
                "title": "Minimal test",
                "expected_result": "Success.",
                "classification": "positive",
            }
        ]))
        tc = test_cases[0]
        assert tc.preconditions is None
        assert tc.steps is None

    def test_test_case_requirement_id_is_set(self):
        _, _, test_cases = self._parse(_valid_llm_response(), requirement_id=99)
        assert all(tc.requirement_id == 99 for tc in test_cases)

    # --- Malformed response tests ---

    def test_missing_refined_requirement_key_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = {k: v for k, v in _valid_llm_response().items() if k != "refined_requirement"}
        with pytest.raises(MalformedRefinementError, match="refined_requirement"):
            self._parse(raw)

    def test_empty_refined_requirement_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = _valid_llm_response(refined_requirement="   ")
        with pytest.raises(MalformedRefinementError):
            self._parse(raw)

    def test_missing_acceptance_criteria_key_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = {k: v for k, v in _valid_llm_response().items() if k != "acceptance_criteria"}
        with pytest.raises(MalformedRefinementError, match="acceptance_criteria"):
            self._parse(raw)

    def test_acceptance_criteria_not_a_list_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = _valid_llm_response(acceptance_criteria="not a list")
        with pytest.raises(MalformedRefinementError):
            self._parse(raw)

    def test_acceptance_criteria_empty_list_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = _valid_llm_response(acceptance_criteria=[])
        with pytest.raises(MalformedRefinementError):
            self._parse(raw)

    def test_missing_test_cases_key_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = {k: v for k, v in _valid_llm_response().items() if k != "test_cases"}
        with pytest.raises(MalformedRefinementError, match="test_cases"):
            self._parse(raw)

    def test_test_cases_not_a_list_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = _valid_llm_response(test_cases="not a list")
        with pytest.raises(MalformedRefinementError):
            self._parse(raw)

    def test_all_test_cases_invalid_classification_raises(self):
        from app.services.refiner import MalformedRefinementError

        raw = _valid_llm_response(test_cases=[
            {"title": "T", "expected_result": "R", "classification": "UNKNOWN"},
        ])
        with pytest.raises(MalformedRefinementError):
            self._parse(raw)

    def test_invalid_test_case_skipped_valid_one_kept(self):
        """An invalid test case is skipped; a valid one in the same list is kept."""
        raw = _valid_llm_response(test_cases=[
            {"title": "Bad", "expected_result": "R", "classification": "BOGUS"},
            {"title": "Good", "expected_result": "Success.", "classification": "positive"},
        ])
        _, _, test_cases = self._parse(raw)
        assert len(test_cases) == 1
        assert test_cases[0].title == "Good"

    def test_completely_empty_response_raises(self):
        from app.services.refiner import MalformedRefinementError

        with pytest.raises(MalformedRefinementError):
            self._parse({})


# ---------------------------------------------------------------------------
# TestRefineRequirement — full pipeline with in-memory DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRefineRequirement:
    async def test_successful_refinement_returns_all_three_objects(self, db_session):
        """A valid LLM response produces RefinedRequirement, AC, and TestCases."""
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            refined_req, ac, test_cases = await refine_requirement(req, findings, db_session)
            await db_session.commit()

        assert refined_req.id is not None
        assert ac.id is not None
        assert len(test_cases) >= 1
        assert all(tc.id is not None for tc in test_cases)

    async def test_refined_requirement_persisted_to_db(self, db_session):
        """RefinedRequirementModel is retrievable from the DB after commit."""
        from sqlalchemy import select
        from app.models.db import RefinedRequirementModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        expected_text = "The system shall respond within 200 ms under normal load."

        with patch(PATCH_TARGET, return_value=_valid_llm_response(
            refined_requirement=expected_text
        )):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        rows = (await db_session.execute(select(RefinedRequirementModel))).scalars().all()
        assert len(rows) == 1
        assert rows[0].text == expected_text
        assert rows[0].requirement_id == req.id

    async def test_acceptance_criteria_persisted_to_db(self, db_session):
        """AcceptanceCriteriaModel is retrievable from the DB after commit."""
        from sqlalchemy import select
        from app.models.db import AcceptanceCriteriaModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        criteria = [
            "Given a valid request, when submitted, then respond within 200 ms.",
            "System shall log each request.",
        ]

        with patch(PATCH_TARGET, return_value=_valid_llm_response(
            acceptance_criteria=criteria
        )):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        rows = (await db_session.execute(select(AcceptanceCriteriaModel))).scalars().all()
        assert len(rows) == 1
        assert rows[0].criteria == criteria

    async def test_test_cases_persisted_to_db(self, db_session):
        """TestCaseModels are retrievable from the DB after commit."""
        from sqlalchemy import select
        from app.models.db import TestCaseModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        rows = (await db_session.execute(select(TestCaseModel))).scalars().all()
        assert len(rows) == 3  # default response has 3 test cases
        classifications = {r.classification for r in rows}
        assert "positive" in classifications
        assert "negative" in classifications
        assert "edge" in classifications

    async def test_requirement_status_updated_to_refined(self, db_session):
        """Requirement status is updated to REFINED after successful refinement."""
        from sqlalchemy import select
        from app.models.db import RequirementModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        req_id = req.id

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        rows = (await db_session.execute(
            select(RequirementModel).where(RequirementModel.id == req_id)
        )).scalars().all()
        assert rows[0].status == "REFINED"

    async def test_llm_api_failure_raises_refinement_error(self, db_session):
        """Both LLM attempts failing raises RefinementError (not LLMError)."""
        from app.services.refiner import RefinementError, refine_requirement
        from app.services.llm_client import LLMError

        req, findings = await _seed_analyzed_requirement(db_session)

        with patch(PATCH_TARGET, side_effect=LLMError("connection refused")):
            with pytest.raises(RefinementError):
                await refine_requirement(req, findings, db_session)

    async def test_llm_failure_does_not_persist_partial_data(self, db_session):
        """When LLM fails, no partial DB records are created."""
        from sqlalchemy import select
        from app.models.db import RefinedRequirementModel, AcceptanceCriteriaModel, TestCaseModel
        from app.services.refiner import RefinementError, refine_requirement
        from app.services.llm_client import LLMError

        req, findings = await _seed_analyzed_requirement(db_session)

        with pytest.raises(RefinementError):
            with patch(PATCH_TARGET, side_effect=LLMError("down")):
                await refine_requirement(req, findings, db_session)

        await db_session.rollback()

        assert len((await db_session.execute(select(RefinedRequirementModel))).scalars().all()) == 0
        assert len((await db_session.execute(select(AcceptanceCriteriaModel))).scalars().all()) == 0
        assert len((await db_session.execute(select(TestCaseModel))).scalars().all()) == 0

    async def test_retry_succeeds_on_second_attempt(self, db_session):
        """First LLM call fails; second succeeds — refinement is returned."""
        from app.services.refiner import refine_requirement
        from app.services.llm_client import LLMError

        req, findings = await _seed_analyzed_requirement(db_session)

        call_count = 0

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise LLMError("transient error")
            return _valid_llm_response()

        with patch(PATCH_TARGET, side_effect=_side_effect):
            refined_req, ac, test_cases = await refine_requirement(req, findings, db_session)
            await db_session.commit()

        assert call_count == 2
        assert refined_req.id is not None

    async def test_malformed_response_raises_malformed_error(self, db_session):
        """An LLM response missing required keys raises MalformedRefinementError."""
        from app.services.refiner import MalformedRefinementError, refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)

        with patch(PATCH_TARGET, return_value={"oops": "garbage"}):
            with pytest.raises(MalformedRefinementError):
                await refine_requirement(req, findings, db_session)

    async def test_refinement_with_no_findings(self, db_session):
        """Refinement works correctly even when findings list is empty."""
        from app.services.refiner import refine_requirement

        req, _ = await _seed_analyzed_requirement(db_session)
        # Use empty findings to simulate a clean requirement.
        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            refined_req, ac, test_cases = await refine_requirement(req, [], db_session)
            await db_session.commit()

        assert refined_req.id is not None
        assert len(ac.criteria) >= 1

    async def test_positive_test_case_generated(self, db_session):
        """Positive test case is generated and persisted."""
        from sqlalchemy import select
        from app.models.db import TestCaseModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        rows = (await db_session.execute(select(TestCaseModel))).scalars().all()
        positive_cases = [r for r in rows if r.classification == "positive"]
        assert len(positive_cases) >= 1

    async def test_negative_test_case_generated(self, db_session):
        """Negative test case is generated and persisted."""
        from sqlalchemy import select
        from app.models.db import TestCaseModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        rows = (await db_session.execute(select(TestCaseModel))).scalars().all()
        negative_cases = [r for r in rows if r.classification == "negative"]
        assert len(negative_cases) >= 1

    async def test_edge_test_case_generated(self, db_session):
        """Edge test case is generated and persisted."""
        from sqlalchemy import select
        from app.models.db import TestCaseModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        rows = (await db_session.execute(select(TestCaseModel))).scalars().all()
        edge_cases = [r for r in rows if r.classification == "edge"]
        assert len(edge_cases) >= 1


# ---------------------------------------------------------------------------
# TestTraceability — ORM relationship chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTraceability:
    """Verify that the full Document → Requirement → Findings → RefinedReq → AC → TestCases
    chain is correctly linked via SQLAlchemy relationships."""

    async def test_refined_requirement_linked_via_relationship(self, db_session):
        """RequirementModel.refined_requirement holds the correct RefinedRequirementModel."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.db import RequirementModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        req_id = req.id

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        # Reload with eager loading to avoid async lazy-load errors.
        db_req = (await db_session.execute(
            select(RequirementModel)
            .where(RequirementModel.id == req_id)
            .options(selectinload(RequirementModel.refined_requirement))
        )).scalar_one()

        assert db_req.refined_requirement is not None
        assert db_req.refined_requirement.requirement_id == req_id

    async def test_acceptance_criteria_linked_via_relationship(self, db_session):
        """RequirementModel.acceptance_criteria list contains the persisted AC."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.db import RequirementModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        req_id = req.id

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        db_req = (await db_session.execute(
            select(RequirementModel)
            .where(RequirementModel.id == req_id)
            .options(selectinload(RequirementModel.acceptance_criteria))
        )).scalar_one()

        assert len(db_req.acceptance_criteria) == 1
        assert db_req.acceptance_criteria[0].requirement_id == req_id

    async def test_test_cases_linked_via_relationship(self, db_session):
        """RequirementModel.test_cases list contains the persisted TestCaseModels."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.db import RequirementModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        req_id = req.id

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        db_req = (await db_session.execute(
            select(RequirementModel)
            .where(RequirementModel.id == req_id)
            .options(selectinload(RequirementModel.test_cases))
        )).scalar_one()

        assert len(db_req.test_cases) == 3
        assert all(tc.requirement_id == req_id for tc in db_req.test_cases)

    async def test_findings_still_linked_after_refinement(self, db_session):
        """Existing Findings remain linked to the requirement after refinement."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.db import RequirementModel
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        req_id = req.id

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        db_req = (await db_session.execute(
            select(RequirementModel)
            .where(RequirementModel.id == req_id)
            .options(selectinload(RequirementModel.findings))
        )).scalar_one()

        assert len(db_req.findings) == 2

    async def test_full_traceability_chain_consistent(self, db_session):
        """All IDs in the traceability chain are consistent and non-None."""
        from sqlalchemy import select
        from app.models.db import (
            AcceptanceCriteriaModel,
            FindingModel,
            RefinedRequirementModel,
            RequirementModel,
            TestCaseModel,
        )
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        req_id = req.id

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        # Load all objects.
        db_req = (await db_session.execute(
            select(RequirementModel).where(RequirementModel.id == req_id)
        )).scalar_one()
        db_findings = (await db_session.execute(
            select(FindingModel).where(FindingModel.requirement_id == req_id)
        )).scalars().all()
        db_refined = (await db_session.execute(
            select(RefinedRequirementModel).where(
                RefinedRequirementModel.requirement_id == req_id
            )
        )).scalar_one()
        db_ac = (await db_session.execute(
            select(AcceptanceCriteriaModel).where(
                AcceptanceCriteriaModel.requirement_id == req_id
            )
        )).scalars().all()
        db_tcs = (await db_session.execute(
            select(TestCaseModel).where(TestCaseModel.requirement_id == req_id)
        )).scalars().all()

        # All IDs must be set.
        assert db_req.id is not None
        assert all(f.id is not None for f in db_findings)
        assert db_refined.id is not None
        assert all(a.id is not None for a in db_ac)
        assert all(tc.id is not None for tc in db_tcs)

        # All foreign keys must point to the same requirement.
        assert all(f.requirement_id == req_id for f in db_findings)
        assert db_refined.requirement_id == req_id
        assert all(a.requirement_id == req_id for a in db_ac)
        assert all(tc.requirement_id == req_id for tc in db_tcs)

    async def test_traceability_entry_can_be_built(self, db_session):
        """A TraceabilityEntry schema can be constructed from the persisted data."""
        from sqlalchemy import select
        from app.models.db import (
            AcceptanceCriteriaModel,
            FindingModel,
            RefinedRequirementModel,
            TestCaseModel,
        )
        from app.models.schemas import TraceabilityEntry
        from app.services.refiner import refine_requirement

        req, findings = await _seed_analyzed_requirement(db_session)
        req_id = req.id

        with patch(PATCH_TARGET, return_value=_valid_llm_response()):
            await refine_requirement(req, findings, db_session)
            await db_session.commit()

        # Gather IDs.
        finding_ids = [
            f.id for f in (
                await db_session.execute(
                    select(FindingModel).where(FindingModel.requirement_id == req_id)
                )
            ).scalars().all()
        ]
        refined_req = (await db_session.execute(
            select(RefinedRequirementModel).where(
                RefinedRequirementModel.requirement_id == req_id
            )
        )).scalar_one()
        ac_ids = [
            a.id for a in (
                await db_session.execute(
                    select(AcceptanceCriteriaModel).where(
                        AcceptanceCriteriaModel.requirement_id == req_id
                    )
                )
            ).scalars().all()
        ]
        tc_ids = [
            tc.id for tc in (
                await db_session.execute(
                    select(TestCaseModel).where(TestCaseModel.requirement_id == req_id)
                )
            ).scalars().all()
        ]

        entry = TraceabilityEntry(
            requirement_id=req_id,
            finding_ids=finding_ids,
            refined_requirement_id=refined_req.id,
            acceptance_criteria_ids=ac_ids,
            test_case_ids=tc_ids,
        )

        assert entry.requirement_id == req_id
        assert entry.refined_requirement_id == refined_req.id
        assert len(entry.finding_ids) == 2
        assert len(entry.test_case_ids) == 3
