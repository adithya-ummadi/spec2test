Spec2Test

AI-Assisted Requirements Quality Gate & Test Generation

Spec2Test is an AI-assisted requirements engineering tool that helps software teams identify quality issues in requirements, improve unclear specifications, generate acceptance criteria and test cases, and maintain traceability from the original requirement to its resulting tests.

Built as an MVP for the IBM Bob 2.0 Hackathon.

🚀 The Problem

Software requirements are often written in natural language and can contain:

Ambiguous statements

Missing information

Contradictory requirements

Requirements that are difficult to test

Vague acceptance conditions

These problems can move downstream into design, implementation, and testing, where they become more expensive to fix.

Spec2Test provides an AI-assisted quality gate before requirements move further into the software development lifecycle.

💡 What Spec2Test Does

Requirement Document
        ↓
Text Extraction
        ↓
Requirement Segmentation
        ↓
AI Quality Analysis
        ↓
Findings + Confidence + Evidence
        ↓
Requirement Refinement
        ↓
Acceptance Criteria + Test Cases
        ↓
Traceability

The system analyzes requirements for:

Ambiguity

Missing Information

Contradiction

Testability

It then helps refine selected requirements and generate acceptance criteria and test cases.

AI output is presented as assisted analysis with confidence and evidence rather than as guaranteed truth.

✨ Key Features

📄 Multi-format Document Processing

Supports:

PDF

DOCX

TXT

Markdown

🔎 Requirement Segmentation

The deterministic processing pipeline identifies individual requirements using:

Numbered lists

Bullet points

Requirement keywords

Table rows

Paragraph boundaries

🤖 AI-Assisted Requirement Analysis

Each requirement can be analyzed for:

Finding Type

Purpose

AMBIGUITY

Detect unclear or vague wording

MISSING_INFORMATION

Identify incomplete information

CONTRADICTION

Identify conflicting statements

TESTABILITY

Identify requirements that are difficult to verify

📊 Confidence Levels

Findings can include:

CONFIRMED

LIKELY

POSSIBLE

INFORMATIONAL

✍️ Requirement Refinement

A requirement can be refined using its original text and analysis findings to produce:

Improved requirement wording

Acceptance criteria

Test cases

🧪 Test Case Generation

Generated tests can cover:

Positive scenarios

Negative scenarios

Edge/boundary cases where applicable

🔗 Traceability

Spec2Test maintains:

Document
   ↓
Requirement
   ↓
Finding
   ↓
Refined Requirement
   ↓
Acceptance Criteria
   ↓
Test Case

🏗️ Architecture

┌──────────────────────────────────────────────┐
│                  Frontend                    │
│             HTML / CSS / JavaScript         │
└──────────────────────┬───────────────────────┘
                       ↓
┌──────────────────────────────────────────────┐
│                FastAPI API                   │
│ Documents • Requirements • Analysis          │
│ Refinement • Traceability • Health           │
└──────────────┬───────────────┬───────────────┘
               │               │
               ↓               ↓
┌──────────────────────┐  ┌───────────────────┐
│ Deterministic        │  │ LLM Integration   │
│ Processing           │  │                   │
│ PDF/DOCX/TXT/MD      │  │ Analysis          │
│ Extraction           │  │ Refinement        │
│ Requirement          │  │ Acceptance        │
│ Segmentation         │  │ Criteria          │
└──────────┬───────────┘  │ Test Generation   │
           │              └─────────┬─────────┘
           └──────────────┬─────────┘
                          ↓
               ┌─────────────────────┐
               │ SQLite + SQLAlchemy │
               └─────────────────────┘

📁 Project Structure

spec2test/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models/
│   │   │   ├── schemas.py
│   │   │   └── db.py
│   │   ├── routers/
│   │   │   ├── documents.py
│   │   │   ├── requirements.py
│   │   │   ├── refinement.py
│   │   │   └── traceability.py
│   │   ├── services/
│   │   │   ├── document_processor.py
│   │   │   ├── requirement_segmenter.py
│   │   │   ├── document_service.py
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
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── api.js
├── demo/
├── bob_sessions/
├── .env.example
├── .gitignore
├── README.md
└── spec2test-plan.md

🛠️ Technologies Used

Backend

Python

FastAPI

Pydantic

SQLAlchemy

SQLite

Uvicorn

Document Processing

PyPDF

python-docx

TXT/Markdown parsing

AI

LLM API integration

Structured JSON output

Prompt-based requirement analysis

AI-assisted requirement refinement

Frontend

HTML

CSS

JavaScript

Testing

pytest

pytest-asyncio

FastAPI API testing

Development

Git

GitHub

VS Code

IBM Bob 2.0

🔌 API Endpoints

Documents

Method

Endpoint

Description

POST

/api/documents/upload

Upload a requirements document

GET

/api/documents/{doc_id}

Get document details/status

GET

/api/documents/{doc_id}/requirements

Get requirements

POST

/api/documents/{doc_id}/analyze

Run batch analysis

GET

/api/documents/{doc_id}/traceability

Get traceability

Requirements

Method

Endpoint

Description

GET

/api/requirements/{req_id}

Get requirement details

POST

/api/requirements/{req_id}/analyze

Analyze a requirement

POST

/api/requirements/{req_id}/refine

Refine requirement + AC + tests

GET

/api/requirements/{req_id}/refined

Retrieve refined output

Health

Method

Endpoint

Description

GET

/health

Backend health check

FastAPI documentation:

http://127.0.0.1:8765/docs

⚙️ Setup

1. Clone

git clone <YOUR_GITHUB_REPOSITORY_URL>
cd spec2test

2. Create virtual environment

cd backend
python3 -m venv .venv
source .venv/bin/activate

3. Install dependencies

pip install -r requirements.txt

4. Configure environment variables

Create your .env using .env.example.

Example:

OPENAI_API_KEY=your_api_key_here
DATABASE_URL=sqlite:///./spec2test.db

Never commit real API keys or secrets to GitHub.

5. Start backend

uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload

Then open:

http://127.0.0.1:8765/docs

🧪 Testing

From backend/:

pytest

The current MVP verification reached 154 passed tests with 0 failures. Two PDF-specific tests were skipped because of a missing reportlab dependency in that test environment.

🎬 Demo Workflow

Upload a requirements document.

View extracted requirements.

Analyze a selected requirement.

Inspect finding type, confidence, evidence, and suggested clarification.

Refine the requirement.

Generate acceptance criteria.

Generate test cases.

Open the traceability view.

Example:

"The system should respond quickly."

        ↓

Ambiguity / Missing Information

        ↓

Suggested clarification

        ↓

Measurable refined requirement

        ↓

Acceptance criteria

        ↓

Test case

🤖 IBM Bob 2.0 Usage

IBM Bob was used as an AI-assisted development agent throughout the implementation.

The project was divided into explicit implementation sub-tasks. Bob assisted with:

Project scaffolding

Data models

Document processing

Requirement segmentation

LLM integration

Requirement analysis

Requirement refinement

REST API implementation

Testing

Development documentation

Design decisions and verification

The development remained human-supervised. Generated code and design decisions were reviewed, tested, and adjusted by the development team.

Development evidence and Bob session artifacts are maintained in the bob_sessions/ directory.

🔐 Security & Responsible AI

Spec2Test is an MVP and is not intended to be treated as a production security system.

Never commit API keys.

Do not upload confidential requirements to an external LLM without authorization.

AI-generated findings require human review.

Confidence levels are not guarantees of correctness.

The system does not claim 100% AI accuracy.

Authentication and multi-tenant authorization are outside the current MVP scope.

⚠️ Current Limitations

Complex/scanned PDFs may require OCR or improved extraction.

LLM findings can be incorrect or incomplete.

SQLite is used for the MVP.

No authentication or multi-tenancy.

No message queue or Kubernetes deployment.

The MVP focuses on the core requirements-quality workflow.

🔮 Future Improvements

OCR for scanned requirements

Improved table/layout extraction

Cross-requirement contradiction detection

Domain-specific requirement analysis

RAG/project terminology support

Requirement evaluation datasets

Richer traceability visualization

Authentication and role-based access

PostgreSQL production deployment

Background job queues

CI/CD integration

Cloud deployment

Integration with issue trackers and test management systems

Automated regression analysis when requirements change

🎯 Project Goal

Spec2Test connects requirements engineering and software testing into one traceable workflow:

Understand → Analyze → Refine → Define Acceptance → Test → Trace

The goal is to help software teams turn natural-language requirements into clearer, more testable, and traceable specifications.

🏆 Hackathon

IBM Bob 2.0 Hackathon

Project: Spec2Test

Focus:

AI-assisted software engineering

Requirements engineering

Software quality

Testing

Developer productivity
