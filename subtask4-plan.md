# Sub-Task 4 — Requirement Analysis Pipeline (LLM Integration)

## Top-Level Overview

**Goal:** Implement the LLM-backed analysis service that evaluates each requirement for
ambiguity, missing information, contradictions, and testability, then persists structured
findings to SQLite and updates requirement status to ANALYZED.

**Scope (this sub-task only):**
- `backend/app/services/llm_client.py` — thin OpenAI wrapper
- `backend/app/prompts/analysis_prompt.py` — system prompt, user prompt template, response schema
- `backend/app/services/analyzer.py` — single-requirement analysis logic
- `backend/app/services/analysis_batch.py` — sequential batch runner with persistence
- `backend/tests/test_analyzer.py` — unit tests with mocked LLM client

**Non-goals (explicitly excluded):**
- REST API endpoints
- Refinement / acceptance criteria / test case generation
- Frontend
- Authentication, queues, Redis, Kubernetes

**Key compatibility constraints:**
- Work with existing `RequirementModel` / `FindingModel` / `FindingSchema` / `FindingType` /
  `ConfidenceLevel` without changing them
- Use the existing async SQLAlchemy session pattern (`AsyncSession`, `db.add()`, `await db.flush()`)
- Persist `FindingModel` rows; update `RequirementModel.status` to `"ANALYZED"`

---

## Files to Create

| File | Purpose |
|------|---------|
| `backend/app/services/llm_client.py` | Isolated OpenAI wrapper |
| `backend/app/prompts/__init__.py` | Package marker |
| `backend/app/prompts/analysis_prompt.py` | Prompts + response schema |
| `backend/app/services/analyzer.py` | Single-requirement analyzer |
| `backend/app/services/analysis_batch.py` | Batch runner + persistence |
| `backend/tests/test_analyzer.py` | Unit tests (mocked LLM) |

**`backend/requirements.txt`** — add `openai>=1.0`

---

## Step-by-Step Implementation Plan

### Step 1 — `llm_client.py`

**Intent:** Isolate all OpenAI SDK contact in one place so the rest of the codebase never
imports `openai` directly.

**Public API:**
```
complete(system_prompt: str, user_prompt: str, response_schema: dict) -> dict
```

**Behaviour:**
- Read `OPENAI_API_KEY` from environment; raise `EnvironmentError` at import/call time if absent.
- Default model: `gpt-4o` (override via `OPENAI_MODEL` env var, default `"gpt-4o"`).
- Use `response_format={"type": "json_object"}` for reliable JSON output.
- On `openai.APIError` or `openai.APIConnectionError`: raise a local `LLMError` (defined in
  this module) — do NOT swallow the error silently.
- No retry logic at this layer; retries are handled one level up in `analyzer.py`.
- `response_schema` is passed in the system prompt as a JSON schema description so the model
  knows the exact structure expected. The schema is embedded in the prompt text — the function
  does not use OpenAI function-calling for simplicity.

**Environment variables required:**
- `OPENAI_API_KEY` — required
- `OPENAI_MODEL` — optional, default `"gpt-4o"`

---

### Step 2 — `prompts/analysis_prompt.py`

**Intent:** Define a well-calibrated prompt that returns structured findings without
fabricating evidence.

**Contents:**
1. `SYSTEM_PROMPT: str` — The system prompt string.
   - States the role: "You are a precise requirements analyst."
   - Lists the four finding types with definitions:
     - `AMBIGUITY` — the requirement contains language that can be interpreted in multiple ways
     - `MISSING_INFORMATION` — the requirement omits information needed to implement or test it
     - `CONTRADICTION` — the requirement contains an internal logical conflict
     - `TESTABILITY` — the requirement cannot be verified with a concrete, measurable test
   - Lists the four confidence levels with rules:
     - `CONFIRMED` — clear, unambiguous evidence in the text
     - `LIKELY` — strong inference but some interpretation required
     - `POSSIBLE` — minor indication; reasonable doubt remains
     - `INFORMATIONAL` — general observation; no defect implied
   - **Explicit instruction:** "Do not assign CONFIRMED unless the evidence is a direct verbatim
     quote from the requirement. Do not invent evidence that is not present in the requirement
     text. If there is no finding of a given type, do not include it."
   - Instructs the model to return a JSON object matching the schema exactly.

2. `RESPONSE_SCHEMA: dict` — JSON Schema for the response:
   ```json
   {
     "type": "object",
     "properties": {
       "findings": {
         "type": "array",
         "items": {
           "type": "object",
           "required": ["type", "confidence", "evidence"],
           "properties": {
             "type": {"type": "string", "enum": ["AMBIGUITY","MISSING_INFORMATION","CONTRADICTION","TESTABILITY"]},
             "confidence": {"type": "string", "enum": ["CONFIRMED","LIKELY","POSSIBLE","INFORMATIONAL"]},
             "evidence": {"type": "string"},
             "missing_info": {"type": "string"},
             "suggested_clarification": {"type": "string"}
           }
         }
       }
     },
     "required": ["findings"]
   }
   ```

3. `build_user_prompt(requirement_text: str) -> str` — formats the user turn.
   Returns: `"Analyze the following requirement:\n\n{requirement_text}"`

4. `embed_schema_in_system_prompt(system_prompt: str, schema: dict) -> str` — appends a
   `"Respond with a JSON object matching this schema: ..."` block to the system prompt.
   Used by `analyzer.py` to produce the final combined system prompt.

---

### Step 3 — `analyzer.py`

**Intent:** Accept one `RequirementModel`, call the LLM, validate the response, and return
`FindingModel` objects (not yet persisted — caller handles persistence).

**Public API:**
```
async def analyze_requirement(req: RequirementModel) -> list[FindingModel]
```

**Behaviour:**
1. Build system and user prompts using `analysis_prompt`.
2. Call `llm_client.complete(...)`.
3. On `LLMError`: retry exactly once. If both attempts fail, raise `AnalysisError`
   (defined in this module) — do NOT silently return an empty list.
4. Parse the returned dict: extract `response["findings"]`.
5. For each finding dict, validate using Pydantic:
   - Validate `type` against `FindingType` enum.
   - Validate `confidence` against `ConfidenceLevel` enum.
   - Clamp/reject any fields not in the schema silently.
6. If `findings` key is missing or the list is empty after validation: return `[]`
   (empty list is valid — a clear requirement may have no findings).
7. Construct and return `FindingModel` objects with `requirement_id=req.id` and
   the validated fields. Do NOT add to a session here.

**Error hierarchy (defined in `analyzer.py`):**
- `AnalysisError(Exception)` — raised when the LLM fails after all retries
- `MalformedResponseError(AnalysisError)` — raised when the response cannot be parsed

**Note:** `analyze_requirement` is `async` because it delegates to `llm_client.complete()`,
which wraps a synchronous SDK call using `asyncio.to_thread` to avoid blocking the event loop.

---

### Step 4 — `analysis_batch.py`

**Intent:** Orchestrate batch analysis for all RAW requirements of a document, persist
findings, and update statuses. One failed requirement must not stop the rest.

**Public API:**
```
async def run_batch_analysis(
    db: AsyncSession,
    document_id: int,
) -> dict  # {"analyzed": int, "failed": int, "skipped": int}
```

**Behaviour:**
1. Query all `RequirementModel` rows where `document_id=document_id` and `status="RAW"`.
2. For each requirement (sequentially):
   a. Call `analyzer.analyze_requirement(req)`.
   b. On success:
      - Add each `FindingModel` to `db`.
      - Set `req.status = "ANALYZED"`.
      - `await db.flush()`.
      - Increment `analyzed` counter.
   c. On `AnalysisError`:
      - Log the error (use `logging.getLogger(__name__)`).
      - Set `req.status = "ANALYSIS_FAILED"` (string literal, not in enum — this is a
        transient failure state outside the normal lifecycle).
      - `await db.flush()`.
      - Increment `failed` counter. Continue to next requirement.
3. After the loop, the caller commits the session.
4. Return the summary dict.

**Note on `RequirementStatus` enum:** `"ANALYSIS_FAILED"` is intentionally stored as a
plain string in the DB column (which is `String`, not a DB enum) — consistent with how
the existing code already stores status values. The `RequirementStatus` enum does not need
to be extended for this sub-task.

---

### Step 5 — Tests in `test_analyzer.py`

**Test classes and scenarios:**

#### `TestAnalyzeRequirement`
All tests mock `llm_client.complete` using `unittest.mock.patch`.

| Test | Scenario |
|------|---------|
| `test_valid_single_finding` | LLM returns one AMBIGUITY/LIKELY finding; verify one `FindingModel` returned |
| `test_multiple_findings` | LLM returns findings of all four types; verify count and types |
| `test_all_finding_types` | Each of AMBIGUITY, MISSING_INFORMATION, CONTRADICTION, TESTABILITY appears |
| `test_all_confidence_levels` | Each of CONFIRMED, LIKELY, POSSIBLE, INFORMATIONAL appears |
| `test_empty_findings_list` | LLM returns `{"findings": []}` → `analyze_requirement` returns `[]` |
| `test_malformed_response_missing_key` | LLM returns `{"oops": 1}` → raises `MalformedResponseError` |
| `test_malformed_response_invalid_enum` | LLM returns finding with `type="UNKNOWN"` → invalid finding skipped or `MalformedResponseError` |
| `test_llm_api_failure` | `complete()` raises `LLMError` both attempts → raises `AnalysisError` |
| `test_retry_on_first_failure` | `complete()` raises `LLMError` on first call, succeeds on second → returns findings |
| `test_finding_fields_mapped_correctly` | evidence, missing_info, suggested_clarification are mapped to `FindingModel` |

#### `TestRunBatchAnalysis`
Uses an in-memory SQLite session identical to existing DB tests.

| Test | Scenario |
|------|---------|
| `test_successful_persistence` | Two RAW requirements → both analyzed → findings in DB, status ANALYZED |
| `test_requirement_status_update` | After batch, requirements have status ANALYZED |
| `test_failed_requirement_does_not_corrupt_others` | First req raises `AnalysisError`, second succeeds → second is ANALYZED, first is ANALYSIS_FAILED |
| `test_returns_summary_dict` | Return dict has correct `analyzed`, `failed`, `skipped` counts |
| `test_skips_non_raw_requirements` | A requirement with status ANALYZED is skipped |

**Mocking pattern (consistent with existing tests):**
```python
from unittest.mock import patch, MagicMock

with patch("app.services.analyzer.llm_client.complete") as mock_complete:
    mock_complete.return_value = {"findings": [...]}
    ...
```

---

## Dependencies to Add

Add to `backend/requirements.txt`:
```
openai>=1.0
```

No other new dependencies. `unittest.mock` is stdlib. `pytest-asyncio` is already present.

---

## Traceability Chain

The implementation preserves the full chain:

```
DocumentModel (id)
  └── RequirementModel (document_id → doc.id)
        └── FindingModel (requirement_id → req.id)
```

All foreign keys already exist in the ORM. No schema migrations needed.

---

## Architecture Diagram

```
run_batch_analysis(db, document_id)
  │
  ├── SELECT RequirementModel WHERE status=RAW
  │
  └── for each req:
        │
        analyze_requirement(req)
          │
          ├── build_user_prompt(req.text)
          ├── embed_schema_in_system_prompt(SYSTEM_PROMPT, RESPONSE_SCHEMA)
          │
          └── llm_client.complete(system_prompt, user_prompt, schema)
                │
                └── openai.chat.completions.create(...)
                      response_format={"type": "json_object"}
```

---

## Environment Variables Required

| Variable | Required | Default | Description |
|---------|---------|---------|-------------|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o` | Model to use for analysis |

---

## Limitations & Assumptions

1. **Sequential only:** No parallel LLM calls. Suitable for MVP; batch analysis of large
   documents will be slow.
2. **Single-requirement scope:** Contradiction detection is within one requirement only.
   Cross-requirement contradiction detection is explicitly out of scope.
3. **No streaming:** Standard completion call; the full response arrives at once.
4. **`ANALYSIS_FAILED` status:** Stored as a plain string in the DB column. The
   `RequirementStatus` Pydantic enum is not modified.
5. **openai SDK v1+:** The implementation targets the `openai>=1.0` API
   (`openai.OpenAI().chat.completions.create`). Earlier SDK versions are not supported.
6. **`asyncio.to_thread`:** The synchronous OpenAI SDK call is wrapped in `asyncio.to_thread`
   so it does not block the async event loop.

---

## Status

[ ] pending
