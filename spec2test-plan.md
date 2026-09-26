# Spec2Test — Implementation Plan

## Top-Level Overview

**Goal:** Build a working MVP of Spec2Test, an AI-assisted requirements quality gate, in 48 hours for the IBM Bob 2.0 hackathon.

**Scope:**
- Accept PDF, DOCX, and TXT/Markdown requirements documents
- Extract individual requirements from uploaded documents
- Analyze each requirement for ambiguity, missing information, contradictions, and testability
- Classify every finding with confidence levels (CONFIRMED / LIKELY / POSSIBLE / INFORMATIONAL) plus supporting evidence
- Suggest clarifications, generate refined requirements, acceptance criteria, and test cases
- Expose a clean REST API (FastAPI) consumed by a minimal frontend
- Maintain a simple in-memory / SQLite traceability model linking: document → requirement → findings → refined requirement → acceptance criteria → test cases

**Non-goals:**
- No microservices, message queues, or Kubernetes
- No complex databases (SQLite or in-memory only)
- No authentication or multi-tenancy
- No real-time streaming (polling is fine for MVP)
- No claim of 100% accuracy from the AI — always surface confidence levels and evidence

**Team split:**
- **You (backend):** Python/FastAPI, document processing, requirement extraction, analysis, LLM integration, acceptance criteria/test generation
- **Teammate (frontend):** UI/UX, dashboard, requirement detail views, traceability visualization, integration

---

## Sub-Task 1 — Project Scaffolding

**Status:** [ ] pending

### Intent
Establish the folder structure, dependency files, and environment baseline so both team members can start in parallel immediately.

### Expected Outcomes
- `backend/` and `frontend/` directories exist with correct structure
- `pyproject.toml` (or `requirements.txt`) lists all backend dependencies
- `frontend/` has a minimal `index.html` + vanilla JS shell (no framework required unless team decides otherwise)
- A root `README.md` describes how to run each side
- A `.env.example` lists required environment variables

### Todo List
1. Create `backend/` with sub-directories: `app/`, `app/routers/`, `app/services/`, `app/models/`, `app/utils/`
2. Create `backend/requirements.txt` with: `fastapi`, `uvicorn[standard]`, `python-multipart`, `pydantic`, `pypdf2` or `pdfminer.six`, `python-docx`, `openai` (or `anthropic` — see LLM section), `sqlalchemy`, `aiosqlite`
3. Create `backend/app/main.py` — FastAPI app entry point with CORS and router registration
4. Create `frontend/` with: `index.html`, `styles.css`, `app.js`
5. Create root `.env.example` with `OPENAI_API_KEY`, `DATABASE_URL=sqlite:///./spec2test.db`
6. Create root `README.md` with run instructions

### Relevant Context
- Repository is currently empty; no existing conventions to follow
- Frontend should be vanilla HTML/CSS/JS unless team prefers React — keep it simple

---

## Sub-Task 2 — Data Models

**Status:** [ ] pending

### Intent
Define the canonical Pydantic and SQLAlchemy models that represent the full data lifecycle: document → requirement → finding → refined requirement → acceptance criteria → test case. Getting these right early prevents refactoring across every other sub-task.

### Expected Outcomes
- `backend/app/models/` contains `schemas.py` (Pydantic) and `db.py` (SQLAlchemy ORM)
- All data shapes are settled and agreed on before service code is written
- Enums for `FindingType`, `ConfidenceLevel`, `RequirementStatus` are defined

### Todo List
1. Define `ConfidenceLevel` enum: `CONFIRMED`, `LIKELY`, `POSSIBLE`, `INFORMATIONAL`
2. Define `FindingType` enum: `AMBIGUITY`, `MISSING_INFORMATION`, `CONTRADICTION`, `TESTABILITY`
3. Define `RequirementStatus` enum: `RAW`, `ANALYZED`, `CLARIFIED`, `REFINED`
4. Define Pydantic models:
   - `DocumentUploadResponse` — id, filename, status, requirement_count
   - `Requirement` — id, document_id, text, source_location, status
   - `Finding` — id, requirement_id, type, confidence, evidence, missing_info, suggested_clarification
   - `RefinedRequirement` — id, requirement_id, text
   - `AcceptanceCriteria` — id, requirement_id, criteria (list of strings)
   - `TestCase` — id, requirement_id, title, preconditions, steps, expected_result, classification (positive/negative/edge)
   - `TraceabilityEntry` — requirement_id, finding_ids, refined_requirement_id, acceptance_criteria_ids, test_case_ids
5. Define SQLAlchemy ORM tables mirroring the above models
6. Create `backend/app/database.py` with SQLite engine setup and `get_db` dependency

### Relevant Context
- SQLite is sufficient; use SQLAlchemy async with `aiosqlite` for non-blocking I/O
- Keep foreign-key relationships simple: Document → Requirement (one-to-many), Requirement → Finding/RefinedReq/AC/TestCase (one-to-many)

---

## Sub-Task 3 — Document Processing Pipeline

**Status:** [ ] pending

### Intent
Build a deterministic service that extracts raw text from uploaded PDF, DOCX, and TXT/Markdown files, then segments that text into individual requirement strings.

### Expected Outcomes
- `backend/app/services/document_processor.py` accepts a file bytes + mime type and returns a list of raw requirement strings
- Handles all three formats (PDF, DOCX, TXT/MD)
- Extraction is deterministic — no LLM involvement at this stage
- Requirements are segmented by common heuristics (numbered lists, "shall", "must", bullet points, table rows)

### Todo List
1. Create `backend/app/utils/file_utils.py` — detect file type from extension/mime, read bytes
2. Create `backend/app/services/document_processor.py`:
   - `extract_text_from_pdf(file_bytes) -> str` using `pdfminer.six`
   - `extract_text_from_docx(file_bytes) -> str` using `python-docx`
   - `extract_text_from_txt(file_bytes) -> str` — decode UTF-8
3. Create `backend/app/services/requirement_segmenter.py`:
   - `segment_requirements(text: str) -> list[str]`
   - Heuristics: numbered items (`1.`, `FR-1`), bullet points, lines containing "shall"/"must"/"should", table rows
   - Fall back: split by double newline for plain paragraphs
4. Wire these into `DocumentService.process_upload(file) -> list[Requirement]`
5. Persist extracted requirements to SQLite with status `RAW`

### Relevant Context
- This sub-task is entirely deterministic — no LLM
- PDF extraction quality varies; for MVP, `pdfminer.six` is sufficient
- Source location (page number / line number) should be stored for traceability

---

## Sub-Task 4 — Requirement Analysis Pipeline (LLM Integration)

**Status:** [ ] pending

### Intent
Build the LLM-backed analysis service that evaluates each requirement for ambiguity, missing information, contradictions, and testability, returning structured findings with confidence levels and evidence.

### Expected Outcomes
- `backend/app/services/analyzer.py` takes a `Requirement` and returns a list of `Finding` objects
- All LLM calls use structured output / function calling to guarantee parseable JSON responses
- Confidence is explicitly set by the LLM prompt — the system never claims certainty it does not have
- Findings are persisted to SQLite

### Todo List
1. Create `backend/app/services/llm_client.py`:
   - Thin wrapper around the chosen LLM SDK (OpenAI `gpt-4o` preferred for structured output support)
   - `complete(system_prompt, user_prompt, response_schema) -> dict`
   - Read API key from environment variable
2. Create `backend/app/prompts/analysis_prompt.py`:
   - System prompt instructs the model: role, task, output format, confidence calibration instructions, and the explicit directive NOT to claim certainty
   - User prompt template inserts the requirement text
   - Response schema (JSON Schema / Pydantic) defines the array of findings
3. Create `backend/app/services/analyzer.py`:
   - `analyze_requirement(req: Requirement) -> list[Finding]`
   - Calls `llm_client.complete()` with analysis prompt
   - Parses structured response into `Finding` objects
   - Handles LLM errors gracefully (retry once, then mark requirement as `ANALYSIS_FAILED`)
4. Create batch runner `backend/app/services/analysis_batch.py`:
   - Iterates over all `RAW` requirements for a document
   - Analyzes sequentially (no parallel LLM calls for MVP)
   - Updates requirement status to `ANALYZED`
5. Persist all findings to SQLite

### Relevant Context
- Use OpenAI function calling / `response_format={"type": "json_object"}` for reliable JSON output
- The LLM prompt must include the four finding types and five confidence levels as enumerations
- The model must be instructed to provide `evidence` (the specific text that triggered the finding), `missing_info`, and `suggested_clarification`
- Contradiction detection within a single requirement is straightforward; cross-requirement contradiction detection is a stretch goal only if time permits

---

## Sub-Task 5 — Clarification & Refinement Pipeline (LLM Integration)

**Status:** [ ] pending

### Intent
Given a requirement and its findings, use the LLM to generate a refined (improved) version of the requirement, a set of acceptance criteria, and one or more test cases.

### Expected Outcomes
- `backend/app/services/refiner.py` produces `RefinedRequirement`, `AcceptanceCriteria`, and `TestCase` objects for a given requirement
- All outputs are persisted and linked in the traceability model
- The pipeline can be triggered per-requirement on demand (not automatically after analysis)

### Todo List
1. Create `backend/app/prompts/refinement_prompt.py`:
   - Takes original requirement text + list of findings
   - Asks LLM to produce: refined requirement text, list of acceptance criteria (Given/When/Then or plain bullet), and 1–3 test cases (title, preconditions, steps, expected result, classification)
2. Create `backend/app/services/refiner.py`:
   - `refine_requirement(req: Requirement, findings: list[Finding]) -> tuple[RefinedRequirement, AcceptanceCriteria, list[TestCase]]`
   - Calls LLM with refinement prompt
   - Parses structured response
3. Persist `RefinedRequirement`, `AcceptanceCriteria`, and `TestCase` to SQLite
4. Update `TraceabilityEntry` for the requirement

### Relevant Context
- Test case generation should include at minimum: one positive test, one negative test (invalid input or boundary), one edge case where applicable
- Acceptance criteria format: prefer Given/When/Then for user stories, bullet points for technical requirements
- This pipeline is triggered by the frontend's "Refine" button — it is not automatic

---

## Sub-Task 6 — REST API Layer

**Status:** [ ] pending

### Intent
Expose all backend capabilities as clean FastAPI endpoints that the frontend will consume. This is the integration layer; no business logic lives here.

### Expected Outcomes
- All endpoints documented via FastAPI's auto-generated OpenAPI/Swagger UI at `/docs`
- Responses follow consistent JSON envelope shape
- File upload endpoint handles multipart correctly

### Todo List
1. Create `backend/app/routers/documents.py`:
   - `POST /api/documents/upload` — accept multipart file, trigger processing, return `DocumentUploadResponse`
   - `GET /api/documents` — list all uploaded documents
   - `GET /api/documents/{doc_id}` — document detail with requirement count
2. Create `backend/app/routers/requirements.py`:
   - `GET /api/documents/{doc_id}/requirements` — list requirements with their findings
   - `GET /api/requirements/{req_id}` — single requirement detail
   - `POST /api/requirements/{req_id}/analyze` — trigger analysis for one requirement
   - `POST /api/documents/{doc_id}/analyze-all` — trigger batch analysis
3. Create `backend/app/routers/refinement.py`:
   - `POST /api/requirements/{req_id}/refine` — trigger refinement pipeline
   - `GET /api/requirements/{req_id}/refined` — get refined requirement + AC + test cases
4. Create `backend/app/routers/traceability.py`:
   - `GET /api/documents/{doc_id}/traceability` — full traceability matrix for a document
5. Wire all routers into `main.py` with `/api` prefix and CORS enabled for `localhost:*`

### Relevant Context
- All endpoints should return HTTP 200 with a `{"data": ..., "error": null}` envelope, or `{"data": null, "error": "message"}` on failure
- Use FastAPI's `BackgroundTasks` for the `analyze-all` endpoint so the response returns immediately while analysis runs in the background
- Analysis status can be polled via `GET /api/documents/{doc_id}` which includes a `status` field

---

## Sub-Task 7 — Frontend Shell

**Status:** [ ] pending

### Intent
Build a minimal, functional frontend that covers the full workflow: upload → requirements list → findings detail → refine → traceability. Vanilla HTML/CSS/JS unless the team decides on a lightweight framework.

### Expected Outcomes
- Single-page app (SPA) with hash-based routing (`#/upload`, `#/documents/:id`, `#/requirements/:id`)
- Displays all API data correctly
- Works in a modern browser without a build step

### Todo List
1. `frontend/index.html` — app shell with nav, router outlet `<div id="app">`
2. `frontend/styles.css` — minimal functional styles (CSS variables, card layout, badge colors for confidence levels)
3. `frontend/app.js` — hash router, fetch wrappers, view rendering functions
4. **Upload view** — file picker, upload button, progress indicator, redirects to document view on success
5. **Document view** — requirement list showing: requirement text (truncated), finding count, confidence badge (worst confidence shown), status chip; "Analyze All" button
6. **Requirement detail view** — full requirement text, findings list (type badge, confidence badge, evidence quote, suggested clarification), "Refine" button
7. **Refined view** — refined requirement text, acceptance criteria list, test cases table (title, steps, expected result, classification badge)
8. **Traceability view** — table mapping requirement → findings count → refined → AC count → test case count; each cell links to relevant view

### Relevant Context
- Confidence level badge colors: CONFIRMED=red, LIKELY=orange, POSSIBLE=yellow, INFORMATIONAL=blue
- Finding type labels: AMBIGUITY, MISSING_INFORMATION, CONTRADICTION, TESTABILITY
- The teammate owns this sub-task; backend API must be stable (or mocked) before they start integration
- Consider providing a `frontend/api.js` module with named functions wrapping each endpoint so the teammate does not need to remember URL patterns

---

## Sub-Task 8 — Traceability Model

**Status:** [ ] pending

### Intent
Ensure the full traceability chain (document → requirement → finding → refined requirement → acceptance criteria → test case) is queryable and surfaced in the API and UI.

### Expected Outcomes
- `GET /api/documents/{doc_id}/traceability` returns a flat matrix usable by the frontend
- Each row represents one requirement with counts/links for each downstream artifact
- The traceability view in the frontend renders this matrix

### Todo List
1. Create `backend/app/services/traceability.py`:
   - `build_traceability_matrix(doc_id) -> list[TraceabilityEntry]`
   - Queries SQLite for all requirements and their linked findings, refined reqs, ACs, test cases
2. Add the traceability router endpoint (already listed in Sub-Task 6, step 4)
3. Frontend traceability view renders the matrix (see Sub-Task 7, step 8)

### Relevant Context
- No graph database needed; a simple JOIN query across SQLite tables is sufficient
- For MVP, traceability is read-only and not interactive (no drag-to-link)

---

## Sub-Task 9 — Integration Testing & Demo Preparation

**Status:** [ ] pending

### Intent
Validate the end-to-end workflow with a real requirements document, fix integration bugs, and prepare a demo-ready state.

### Expected Outcomes
- At least one real requirements document (PDF or DOCX) runs through the full pipeline without error
- API responses match frontend expectations
- A short demo script is documented in `README.md`

### Todo List
1. Create `tests/test_document_processor.py` — unit tests for text extraction and segmentation
2. Create `tests/test_analyzer.py` — unit test for finding schema validation (mock LLM)
3. Create `tests/test_api.py` — integration test for upload → analyze → refine endpoints using `httpx` + `pytest`
4. Run end-to-end with a sample SRS document; capture sample output in `demo/sample_output.json`
5. Update `README.md` with: prerequisites, installation steps, how to set the API key, how to run backend, how to run frontend, demo steps
6. Fix any bugs found during integration

### Relevant Context
- Use `pytest` with `pytest-asyncio` for async tests
- Mock the LLM client in unit tests using `unittest.mock.patch`
- A real LLM API key is needed for end-to-end integration test

---

## Architecture Summary

### Folder Structure

```
spec2test/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models/
│   │   │   ├── schemas.py          # Pydantic models
│   │   │   └── db.py               # SQLAlchemy ORM models
│   │   ├── routers/
│   │   │   ├── documents.py
│   │   │   ├── requirements.py
│   │   │   ├── refinement.py
│   │   │   └── traceability.py
│   │   ├── services/
│   │   │   ├── document_processor.py
│   │   │   ├── requirement_segmenter.py
│   │   │   ├── llm_client.py
│   │   │   ├── analyzer.py
│   │   │   ├── analysis_batch.py
│   │   │   ├── refiner.py
│   │   │   └── traceability.py
│   │   ├── prompts/
│   │   │   ├── analysis_prompt.py
│   │   │   └── refinement_prompt.py
│   │   └── utils/
│   │       └── file_utils.py
│   ├── tests/
│   │   ├── test_document_processor.py
│   │   ├── test_analyzer.py
│   │   └── test_api.py
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── api.js
├── demo/
│   └── sample_output.json
├── .env.example
└── README.md
```

### API Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/documents/upload` | Upload a document |
| GET | `/api/documents` | List documents |
| GET | `/api/documents/{id}` | Document detail |
| GET | `/api/documents/{id}/requirements` | Requirements for document |
| POST | `/api/documents/{id}/analyze-all` | Batch analyze |
| GET | `/api/requirements/{id}` | Requirement detail |
| POST | `/api/requirements/{id}/analyze` | Analyze one requirement |
| POST | `/api/requirements/{id}/refine` | Refine requirement |
| GET | `/api/requirements/{id}/refined` | Get refined output |
| GET | `/api/documents/{id}/traceability` | Traceability matrix |

### Deterministic vs LLM

| Component | Approach |
|-----------|----------|
| File type detection | Deterministic |
| Text extraction (PDF/DOCX/TXT) | Deterministic |
| Requirement segmentation | Deterministic (heuristics) |
| Finding detection | LLM |
| Confidence classification | LLM (prompted) |
| Suggested clarification | LLM |
| Refined requirement | LLM |
| Acceptance criteria | LLM |
| Test case generation | LLM |
| Traceability linking | Deterministic (DB joins) |

### Technical Risks

| Risk | Mitigation |
|------|------------|
| LLM returns unparseable JSON | Use OpenAI structured output / JSON mode; validate with Pydantic; retry once |
| PDF extraction loses structure | Use `pdfminer.six`; fall back to raw text; warn the user in the UI |
| Requirement segmentation misses items | Heuristics cover 80% of cases; provide a manual add/edit fallback in the UI (stretch goal) |
| LLM API rate limits or latency | Process sequentially; add a loading indicator; do not parallelize LLM calls |
| CORS issues during development | Enable CORS for all origins in dev; restrict in prod config |
| SQLite concurrency | Single-writer SQLite is fine for a single-server MVP; use async SQLAlchemy |
| Cross-requirement contradiction detection | Descope for MVP; flag only within single requirements |

---

## Recommended Implementation Order (48-hour hackathon)

**Hours 0–4:** Sub-Task 1 (scaffolding) + Sub-Task 2 (data models) — both team members aligned on data shapes  
**Hours 4–10:** Sub-Task 3 (document processing) + Sub-Task 7 (frontend shell begins in parallel)  
**Hours 10–18:** Sub-Task 4 (analysis pipeline) + Sub-Task 6 (API layer begins)  
**Hours 18–24:** Sub-Task 5 (refinement pipeline) + Sub-Task 6 (API layer completes) + Sub-Task 7 (frontend integration begins)  
**Hours 24–36:** Sub-Task 8 (traceability) + Sub-Task 7 (frontend polish)  
**Hours 36–44:** Sub-Task 9 (integration testing, bug fixing, demo prep)  
**Hours 44–48:** Buffer — polish UI, record demo, finalize README  
