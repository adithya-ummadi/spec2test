"""Analyzer — single-requirement analysis via the LLM.

Public API
----------
analyze_requirement(req) -> list[FindingModel]
    Analyze one requirement and return validated FindingModel objects.
    The caller is responsible for persisting the returned objects.

Error hierarchy
---------------
AnalysisError          — base; raised when analysis fails after all retries
MalformedResponseError — subclass; raised when the LLM response cannot be parsed
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.models.db import FindingModel, RequirementModel
from app.models.schemas import ConfidenceLevel, FindingType
from app.prompts.analysis_prompt import (
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


class AnalysisError(Exception):
    """Raised when requirement analysis fails after all retries."""


class MalformedResponseError(AnalysisError):
    """Raised when the LLM response cannot be parsed into valid findings."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_TYPES = {ft.value for ft in FindingType}
_VALID_CONFIDENCES = {cl.value for cl in ConfidenceLevel}


def _parse_findings(raw: dict[str, Any], requirement_id: int) -> list[FindingModel]:
    """Parse *raw* (the deserialized LLM response) into a list of :class:`FindingModel`.

    - Validates ``type`` and ``confidence`` against the enums.
    - Silently drops individual items with invalid enum values (rather than
      crashing the whole requirement) so that a partially-valid response still
      produces useful findings.
    - Raises :class:`MalformedResponseError` if the top-level ``findings`` key
      is missing entirely (the model returned garbage).
    """
    if "findings" not in raw:
        raise MalformedResponseError(
            f"LLM response is missing the required 'findings' key. Got keys: {list(raw.keys())}"
        )

    finding_list = raw["findings"]

    if not isinstance(finding_list, list):
        raise MalformedResponseError(
            f"'findings' must be a JSON array, got {type(finding_list).__name__}"
        )

    results: list[FindingModel] = []
    for i, item in enumerate(finding_list):
        if not isinstance(item, dict):
            log.warning("Skipping finding[%d]: not a JSON object", i)
            continue

        finding_type = item.get("type")
        confidence = item.get("confidence")
        evidence = item.get("evidence")

        if finding_type not in _VALID_TYPES:
            log.warning(
                "Skipping finding[%d]: invalid type %r (valid: %s)",
                i,
                finding_type,
                sorted(_VALID_TYPES),
            )
            continue

        if confidence not in _VALID_CONFIDENCES:
            log.warning(
                "Skipping finding[%d]: invalid confidence %r (valid: %s)",
                i,
                confidence,
                sorted(_VALID_CONFIDENCES),
            )
            continue

        if not isinstance(evidence, str) or not evidence.strip():
            log.warning(
                "Skipping finding[%d]: 'evidence' must be a non-empty string", i
            )
            continue

        results.append(
            FindingModel(
                requirement_id=requirement_id,
                type=finding_type,
                confidence=confidence,
                evidence=evidence.strip(),
                missing_info=item.get("missing_info") or None,
                suggested_clarification=item.get("suggested_clarification") or None,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyze_requirement(req: RequirementModel) -> list[FindingModel]:
    """Analyze *req* and return a list of :class:`FindingModel` objects.

    The returned objects are NOT added to any database session — that is the
    caller's responsibility.

    Retries once on transient :class:`LLMError`.  If both attempts fail,
    raises :class:`AnalysisError`.

    Raises :class:`MalformedResponseError` (a subclass of :class:`AnalysisError`)
    if the LLM returns a structurally invalid response.

    An empty list is a valid return value — it means the requirement has no
    detectable quality defects.
    """
    system_prompt = RENDERED_SYSTEM_PROMPT
    user_prompt = build_user_prompt(req.text)

    last_exc: Exception | None = None
    for attempt in range(2):  # try up to 2 times
        try:
            # The openai SDK is synchronous; run it in a thread so we do not
            # block the async event loop.
            raw: dict[str, Any] = await asyncio.to_thread(
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
                    "LLM call failed for requirement %d (attempt 1/2): %s. Retrying…",
                    req.id,
                    exc,
                )
            # attempt == 1 falls through to the raise below
    else:
        # Both attempts exhausted.
        raise AnalysisError(
            f"LLM analysis failed for requirement {req.id} after 2 attempts: {last_exc}"
        ) from last_exc

    # MalformedResponseError propagates directly — no retry for parse errors.
    return _parse_findings(raw, requirement_id=req.id)
