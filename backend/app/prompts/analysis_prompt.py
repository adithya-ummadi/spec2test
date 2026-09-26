"""Analysis prompt — system prompt, user prompt builder, and response schema.

This module is the single authoritative source of all prompt text and the JSON
Schema used to request structured output from the LLM.  Nothing outside this
module should construct or modify these strings.
"""

from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Response schema (JSON Schema)
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "description": (
                "Zero or more findings about the requirement. "
                "Return an empty array if the requirement is clear and testable."
            ),
            "items": {
                "type": "object",
                "required": ["type", "confidence", "evidence"],
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "AMBIGUITY",
                            "MISSING_INFORMATION",
                            "CONTRADICTION",
                            "TESTABILITY",
                        ],
                        "description": "The category of the finding.",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["CONFIRMED", "LIKELY", "POSSIBLE", "INFORMATIONAL"],
                        "description": (
                            "How certain you are that this is a real defect. "
                            "CONFIRMED: the evidence is a verbatim quote that makes "
                            "the issue undeniable. "
                            "LIKELY: strong inference, minor interpretation needed. "
                            "POSSIBLE: some indication, reasonable doubt remains. "
                            "INFORMATIONAL: general observation, not necessarily a defect."
                        ),
                    },
                    "evidence": {
                        "type": "string",
                        "description": (
                            "The exact text from the requirement that triggered this "
                            "finding. Must be a direct quote or a specific reference. "
                            "Never fabricate or paraphrase evidence."
                        ),
                    },
                    "missing_info": {
                        "type": "string",
                        "description": (
                            "For MISSING_INFORMATION findings: describe what specific "
                            "information is absent. Omit for other finding types."
                        ),
                    },
                    "suggested_clarification": {
                        "type": "string",
                        "description": (
                            "A concrete suggestion for how to improve or clarify the "
                            "requirement. Optional for all finding types."
                        ),
                    },
                },
            },
        }
    },
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = """\
You are a precise requirements analyst. Your only job is to identify quality \
defects in a single software requirement statement, classify each defect by \
type and confidence, and return the result as structured JSON.

## Finding types

- AMBIGUITY: The requirement contains language that can be interpreted in two or \
more different ways. Example: words like "fast", "easy", "appropriate", "reasonable", \
or "as needed" with no measurable definition.

- MISSING_INFORMATION: The requirement omits information that is necessary to \
implement or test it. Example: no stated actor, no boundary condition, no success \
criterion, no error handling rule.

- CONTRADICTION: The requirement contains two statements that are logically \
incompatible with each other within the same requirement text.

- TESTABILITY: The requirement cannot be verified with a concrete, repeatable, \
measurable test as written. This is often a consequence of AMBIGUITY or \
MISSING_INFORMATION, but should be reported separately when testability is the \
primary concern.

## Confidence levels

Use these levels strictly according to the rules below — do NOT upgrade confidence \
to appear more authoritative:

- CONFIRMED: The evidence is an unambiguous, verbatim excerpt from the requirement \
that makes the defect undeniable. Use this level only when no reasonable interpretation \
of the text avoids the defect.

- LIKELY: The defect is strongly suggested but requires a small inference or \
contextual judgment. The evidence clearly points in one direction.

- POSSIBLE: There is some indication of a defect, but a reasonable reader might \
not agree. The finding is worth noting but has real uncertainty.

- INFORMATIONAL: A general observation or best-practice note. No clear defect is \
present, but the information may help the author improve the requirement.

## Rules you must follow

1. Only report findings that are directly supported by the text of the requirement. \
Do NOT invent scenarios, assume external context, or fabricate evidence.

2. The "evidence" field must be a direct quote or a specific reference to text \
in the requirement. Never paraphrase or construct evidence that is not present.

3. Do NOT assign CONFIRMED unless the defect is unmistakable from the verbatim text.

4. If the requirement is clear, complete, unambiguous, and testable, return an \
empty findings array. An empty array is a valid and correct response.

5. Do NOT report the same defect under multiple finding types unless each type adds \
genuinely distinct information.

6. Respond with a JSON object that matches the schema below exactly. Do not include \
any text outside the JSON object.

{schema_block}
"""


def _build_system_prompt() -> str:
    """Render SYSTEM_PROMPT with the embedded schema block."""
    schema_block = (
        "## Required response schema (JSON Schema)\n\n"
        "```json\n"
        + json.dumps(RESPONSE_SCHEMA, indent=2)
        + "\n```"
    )
    return SYSTEM_PROMPT.format(schema_block=schema_block)


# Pre-rendered so callers pay the formatting cost once at import time.
RENDERED_SYSTEM_PROMPT: str = _build_system_prompt()


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


def build_user_prompt(requirement_text: str) -> str:
    """Return the user-turn prompt for analyzing *requirement_text*."""
    return (
        "Analyze the following requirement and return your findings as JSON.\n\n"
        f"Requirement:\n{requirement_text}"
    )
