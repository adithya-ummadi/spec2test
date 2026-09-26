"""Refinement prompt — system prompt, user prompt builder, and response schema.

This module is the single authoritative source of all prompt text and the JSON
Schema used to request structured refinement output from the LLM.  Nothing
outside this module should construct or modify these strings.

The prompt instructs the model to:
  - Produce a refined/improved version of the requirement using the original
    text and any findings that were identified.
  - Preserve the original intent; never invent unsupported business facts.
  - Remove ambiguity and missing information where possible; add measurable
    and testable wording.
  - Generate acceptance criteria (Given/When/Then where appropriate; plain
    bullets for technical requirements).
  - Generate 1–3 test cases covering positive, negative, and edge scenarios.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.db import FindingModel


# ---------------------------------------------------------------------------
# Response schema (JSON Schema)
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "required": ["refined_requirement", "acceptance_criteria", "test_cases"],
    "additionalProperties": False,
    "properties": {
        "refined_requirement": {
            "type": "string",
            "description": (
                "The improved version of the original requirement. "
                "Must preserve the original intent while removing ambiguity and "
                "adding measurable, testable wording. "
                "Do NOT introduce business facts that are not supported by the "
                "original requirement or its findings."
            ),
        },
        "acceptance_criteria": {
            "type": "array",
            "minItems": 1,
            "description": (
                "A list of acceptance criteria for the refined requirement. "
                "Use Given/When/Then format for user-story style requirements. "
                "Use plain imperative sentences for technical requirements. "
                "Each item must be independently verifiable."
            ),
            "items": {"type": "string"},
        },
        "test_cases": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "description": (
                "Between 1 and 3 test cases. "
                "Include at minimum one positive test. "
                "Include a negative test (invalid input or boundary violation) "
                "if the requirement implies validation or error handling. "
                "Include an edge case if a boundary condition exists."
            ),
            "items": {
                "type": "object",
                "required": ["title", "expected_result", "classification"],
                "additionalProperties": False,
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, descriptive name for the test case.",
                    },
                    "preconditions": {
                        "type": "string",
                        "description": (
                            "State of the system before the test begins. "
                            "Omit if there are no special preconditions."
                        ),
                    },
                    "steps": {
                        "type": "string",
                        "description": (
                            "Numbered list of actions to perform during the test. "
                            "Each step should be concrete and unambiguous."
                        ),
                    },
                    "expected_result": {
                        "type": "string",
                        "description": (
                            "The observable, measurable outcome that indicates the "
                            "test has passed. Must be specific enough to verify."
                        ),
                    },
                    "classification": {
                        "type": "string",
                        "enum": ["positive", "negative", "edge"],
                        "description": (
                            "positive: valid inputs, happy-path scenario. "
                            "negative: invalid inputs, error handling, or boundary violations. "
                            "edge: boundary conditions, extreme values, or unusual but valid states."
                        ),
                    },
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE: str = """\
You are an expert requirements engineer. Your task is to refine a single \
software requirement by using the original requirement text and a list of \
quality findings that were previously identified.

## Your output must contain exactly three things

1. **refined_requirement** — An improved version of the original requirement \
that:
   - Preserves the original intent completely.
   - Eliminates ambiguity by replacing vague terms with measurable definitions.
   - Fills in missing information only when it can be reasonably inferred from \
the original text or its findings — never invent business facts that are not \
supported by the evidence you are given.
   - Uses clear, testable, measurable language (avoid: "fast", "easy", \
"appropriate", "reasonable", "as needed", "etc.").
   - Where information is genuinely absent and cannot be inferred, acknowledge \
the limitation explicitly (e.g. "NOTE: response-time threshold TBD by \
stakeholders") rather than fabricating a value.

2. **acceptance_criteria** — A list of at least one acceptance criterion:
   - Use Given/When/Then format for user-facing or story-style requirements.
   - Use plain imperative statements for technical or system-level requirements.
   - Each criterion must be independently verifiable.

3. **test_cases** — Between 1 and 3 test cases:
   - At least one **positive** case (valid inputs, expected happy-path outcome).
   - At least one **negative** case when the requirement implies validation or \
error handling (invalid inputs, boundary violations, rejection scenarios).
   - An **edge** case when a boundary condition or extreme value is meaningful.
   - Each test case must have a title, an expected_result, and a classification.
   - preconditions and steps are optional but should be included whenever they \
make the test case clearer.

## Rules you must never break

1. Do NOT invent unsupported business facts. If the original requirement does \
not say what a threshold, actor, or system component is, do not make one up. \
Instead, note the ambiguity explicitly in the refined requirement.

2. If a finding describes genuinely missing information that cannot be inferred, \
surface that limitation in the refined requirement text rather than pretending \
certainty.

3. Do NOT include content that is outside the scope of the original requirement.

4. Respond with a JSON object that matches the schema below exactly. Do not \
include any text outside the JSON object.

{schema_block}
"""


def _build_system_prompt() -> str:
    """Render the system prompt with the embedded JSON schema block."""
    schema_block = (
        "## Required response schema (JSON Schema)\n\n"
        "```json\n"
        + json.dumps(RESPONSE_SCHEMA, indent=2)
        + "\n```"
    )
    return _SYSTEM_PROMPT_TEMPLATE.format(schema_block=schema_block)


# Pre-rendered once at import time.
RENDERED_SYSTEM_PROMPT: str = _build_system_prompt()


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


def build_user_prompt(requirement_text: str, findings: list) -> str:
    """Return the user-turn prompt for refining *requirement_text*.

    Parameters
    ----------
    requirement_text:
        The original requirement text as stored in the database.
    findings:
        A list of :class:`~app.models.db.FindingModel` objects (or any objects
        with ``type``, ``confidence``, ``evidence``, ``missing_info``, and
        ``suggested_clarification`` attributes).  May be empty.
    """
    findings_block = _format_findings(findings)
    return (
        "Original requirement:\n"
        f"{requirement_text}\n\n"
        f"{findings_block}\n"
        "Produce the refined requirement, acceptance criteria, and test cases "
        "as a single JSON object."
    )


def _format_findings(findings: list) -> str:
    """Render the findings list as a human-readable block for the prompt."""
    if not findings:
        return (
            "Quality findings: None — the requirement had no identified defects. "
            "Refine it purely for clarity and testability."
        )

    lines = ["Quality findings identified during analysis:"]
    for i, f in enumerate(findings, start=1):
        parts = [
            f"{i}. [{f.type}] (confidence: {f.confidence})",
            f"   Evidence: {f.evidence or 'N/A'}",
        ]
        if getattr(f, "missing_info", None):
            parts.append(f"   Missing information: {f.missing_info}")
        if getattr(f, "suggested_clarification", None):
            parts.append(f"   Suggested clarification: {f.suggested_clarification}")
        lines.extend(parts)

    return "\n".join(lines)
