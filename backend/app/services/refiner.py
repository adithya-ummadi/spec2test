"""Refiner — generate a refined requirement, acceptance criteria, and test cases.

Public API
----------
refine_requirement(req, findings, db) -> tuple[RefinedRequirementModel, AcceptanceCriteriaModel, list[TestCaseModel]]
    Refine one requirement and persist the generated artefacts.
    Returns the persisted ORM objects.

Error hierarchy
---------------
RefinementError          — base; raised when refinement fails
MalformedRefinementError — subclass; raised when the LLM response cannot be parsed
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import (
    AcceptanceCriteriaModel,
    FindingModel,
    RefinedRequirementModel,
    RequirementModel,
    TestCaseModel,
)
from app.prompts.refinement_prompt import (
    RENDERED_SYSTEM_PROMPT,
    RESPONSE_SCHEMA,
    build_user_prompt,
)
from app.services import llm_client
from app.services.llm_client import LLMError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class RefinementError(Exception):
    """Raised when requirement refinement fails after all retries."""


class MalformedRefinementError(RefinementError):
    """Raised when the LLM response cannot be parsed into valid refinement data."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_CLASSIFICATIONS = {"positive", "negative", "edge"}


def _parse_response(
    raw: dict[str, Any],
    requirement_id: int,
) -> tuple[RefinedRequirementModel, AcceptanceCriteriaModel, list[TestCaseModel]]:
    """Parse the raw LLM response dict into ORM objects.

    Raises :class:`MalformedRefinementError` if any required top-level key is
    missing or structurally wrong.  Individual test cases with an invalid
    classification are silently dropped so that a partial response is still
    useful; but at least one valid test case must remain.
    """
    # --- refined_requirement ---
    if "refined_requirement" not in raw:
        raise MalformedRefinementError(
            "LLM response is missing required key 'refined_requirement'. "
            f"Got keys: {list(raw.keys())}"
        )
    refined_text = raw["refined_requirement"]
    if not isinstance(refined_text, str) or not refined_text.strip():
        raise MalformedRefinementError(
            f"'refined_requirement' must be a non-empty string, got: {refined_text!r}"
        )

    # --- acceptance_criteria ---
    if "acceptance_criteria" not in raw:
        raise MalformedRefinementError(
            "LLM response is missing required key 'acceptance_criteria'. "
            f"Got keys: {list(raw.keys())}"
        )
    criteria_list = raw["acceptance_criteria"]
    if not isinstance(criteria_list, list):
        raise MalformedRefinementError(
            f"'acceptance_criteria' must be a JSON array, got {type(criteria_list).__name__}"
        )
    # Filter out any non-string items.
    valid_criteria = [c for c in criteria_list if isinstance(c, str) and c.strip()]
    if not valid_criteria:
        raise MalformedRefinementError(
            "'acceptance_criteria' array is empty or contains no valid string items."
        )

    # --- test_cases ---
    if "test_cases" not in raw:
        raise MalformedRefinementError(
            "LLM response is missing required key 'test_cases'. "
            f"Got keys: {list(raw.keys())}"
        )
    test_case_list = raw["test_cases"]
    if not isinstance(test_case_list, list):
        raise MalformedRefinementError(
            f"'test_cases' must be a JSON array, got {type(test_case_list).__name__}"
        )

    test_case_models: list[TestCaseModel] = []
    for i, tc in enumerate(test_case_list):
        if not isinstance(tc, dict):
            log.warning("Skipping test_case[%d]: not a JSON object", i)
            continue

        title = tc.get("title")
        expected_result = tc.get("expected_result")
        classification = tc.get("classification")

        if not isinstance(title, str) or not title.strip():
            log.warning("Skipping test_case[%d]: 'title' missing or empty", i)
            continue

        if not isinstance(expected_result, str) or not expected_result.strip():
            log.warning(
                "Skipping test_case[%d]: 'expected_result' missing or empty", i
            )
            continue

        if classification not in _VALID_CLASSIFICATIONS:
            log.warning(
                "Skipping test_case[%d]: invalid classification %r (valid: %s)",
                i,
                classification,
                sorted(_VALID_CLASSIFICATIONS),
            )
            continue

        preconditions = tc.get("preconditions") or None
        if isinstance(preconditions, str):
            preconditions = preconditions.strip() or None

        steps = tc.get("steps") or None
        if isinstance(steps, str):
            steps = steps.strip() or None

        test_case_models.append(
            TestCaseModel(
                requirement_id=requirement_id,
                title=title.strip(),
                preconditions=preconditions,
                steps=steps,
                expected_result=expected_result.strip(),
                classification=classification,
            )
        )

    if not test_case_models:
        raise MalformedRefinementError(
            "LLM returned no valid test cases after filtering. "
            f"Raw test_cases: {test_case_list!r}"
        )

    # Build ORM objects (not yet added to any session).
    refined_req = RefinedRequirementModel(
        requirement_id=requirement_id,
        text=refined_text.strip(),
    )

    ac = AcceptanceCriteriaModel(requirement_id=requirement_id)
    ac.criteria = valid_criteria  # uses the property setter that JSON-encodes

    return refined_req, ac, test_case_models


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def refine_requirement(
    req: RequirementModel,
    findings: list[FindingModel],
    db: AsyncSession,
) -> tuple[RefinedRequirementModel, AcceptanceCriteriaModel, list[TestCaseModel]]:
    """Refine *req* using its *findings* and persist the results to *db*.

    Workflow
    --------
    1. Build the refinement prompt from the requirement text and findings.
    2. Call the LLM (retries once on transient :class:`LLMError`).
    3. Parse and validate the structured JSON response.
    4. Persist :class:`RefinedRequirementModel`, :class:`AcceptanceCriteriaModel`,
       and :class:`TestCaseModel` objects to the database session.
    5. Update the requirement status to ``REFINED``.
    6. Flush the session so that IDs are assigned (commit is the caller's
       responsibility).

    Returns
    -------
    tuple
        ``(RefinedRequirementModel, AcceptanceCriteriaModel, list[TestCaseModel])``
        — all persisted ORM objects with their IDs populated after the flush.

    Raises
    ------
    RefinementError
        If the LLM API fails after all retries.
    MalformedRefinementError
        If the LLM returns a structurally invalid response.
    """
    system_prompt = RENDERED_SYSTEM_PROMPT
    user_prompt = build_user_prompt(req.text, findings)

    last_exc: Exception | None = None
    raw: dict[str, Any] | None = None

    for attempt in range(2):  # try up to 2 times
        try:
            # The openai SDK is synchronous; run it in a thread so we don't
            # block the async event loop.
            raw = await asyncio.to_thread(
                llm_client.complete,
                system_prompt,
                user_prompt,
                RESPONSE_SCHEMA,
            )
            break  # success — exit the retry loop
        except LLMError as exc:
            last_exc = exc
            if attempt == 0:
                log.warning(
                    "LLM call failed for refinement of requirement %d "
                    "(attempt 1/2): %s. Retrying…",
                    req.id,
                    exc,
                )
            # attempt == 1 falls through to the raise below
    else:
        raise RefinementError(
            f"LLM refinement failed for requirement {req.id} after 2 attempts: "
            f"{last_exc}"
        ) from last_exc

    # MalformedRefinementError propagates directly — no retry for parse errors.
    refined_req, ac, test_cases = _parse_response(raw, requirement_id=req.id)

    # Persist — add to session.
    db.add(refined_req)
    db.add(ac)
    for tc in test_cases:
        db.add(tc)

    # Update requirement status.
    req.status = "REFINED"

    # Flush to obtain IDs without committing; the caller owns the transaction.
    await db.flush()

    log.info(
        "Requirement %d refined: refined_req_id=%d, ac_id=%d, test_case_ids=%s",
        req.id,
        refined_req.id,
        ac.id,
        [tc.id for tc in test_cases],
    )

    return refined_req, ac, test_cases
