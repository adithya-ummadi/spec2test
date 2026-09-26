"""LLM client — thin, isolated wrapper around the OpenAI Chat Completions API.

All OpenAI SDK imports are confined to this module.  The rest of the application
must not import ``openai`` directly; instead it uses :func:`complete`.

Environment variables
---------------------
OPENAI_API_KEY : str (required)
    Your OpenAI secret key.
OPENAI_MODEL : str (optional, default "gpt-4o")
    The model used for every completion request.
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------------------
# Module-level error type — intentionally not importing openai at module scope
# so that the class is always available for mocking even when openai is absent.
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Raised when the LLM API returns an error or is unreachable.

    Wraps the underlying SDK exception so callers do not need to import
    ``openai`` to catch LLM-related failures.
    """


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "gpt-4o"


def _get_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise LLMError(
            "OPENAI_API_KEY environment variable is not set or is empty. "
            "Set it before running the analysis pipeline."
        )
    return key


def _get_model() -> str:
    return os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def complete(
    system_prompt: str,
    user_prompt: str,
    response_schema: dict | None = None,  # accepted but embedded in system_prompt
) -> dict[str, Any]:
    """Send a chat completion request and return the parsed JSON response.

    Parameters
    ----------
    system_prompt:
        The system-role message.  This should already contain the JSON schema
        instructions (as produced by :mod:`app.prompts.analysis_prompt`).
    user_prompt:
        The user-role message containing the requirement text.
    response_schema:
        Accepted for forward-compatibility but not forwarded to the API —
        the schema is already embedded in *system_prompt*.

    Returns
    -------
    dict
        The parsed JSON object returned by the model.

    Raises
    ------
    LLMError
        If the API returns an error, the connection fails, or the response
        cannot be parsed as JSON.
    """
    try:
        import openai  # imported here to keep the module importable without openai installed
    except ImportError as exc:  # pragma: no cover
        raise LLMError(
            "openai package is not installed. Install it with: pip install openai>=1.0"
        ) from exc

    api_key = _get_api_key()
    model = _get_model()

    client = openai.OpenAI(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,  # deterministic output for structured analysis
        )
    except openai.APIConnectionError as exc:
        raise LLMError(f"Could not connect to the OpenAI API: {exc}") from exc
    except openai.AuthenticationError as exc:
        raise LLMError(
            "OpenAI API authentication failed. Check OPENAI_API_KEY."
        ) from exc
    except openai.RateLimitError as exc:
        raise LLMError(f"OpenAI rate limit exceeded: {exc}") from exc
    except openai.APIStatusError as exc:
        raise LLMError(
            f"OpenAI API error (status {exc.status_code}): {exc.message}"
        ) from exc

    raw_content: str = response.choices[0].message.content or ""

    import json  # stdlib — deferred so it stays next to its use

    try:
        return json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"LLM returned a response that is not valid JSON: {raw_content!r}"
        ) from exc
