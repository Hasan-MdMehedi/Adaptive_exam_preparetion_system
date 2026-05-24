# Adaptive Document Preparation System

An AI-powered adaptive study tool that generates MCQ-based quizzes from a PDF document, tracks your performance in a Knowledge Base, and intelligently adapts future question sets to focus on your weak areas.

Built for the **SLATEFALL Dossier** (50-page PDF, 10 sections) as part of an AI/ML Internship Assessment.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Running the Project](#running-the-project)
- [Evaluation Scenarios](#evaluation-scenarios)
- [How Adaptive Intelligence Works](#how-adaptive-intelligence-works)
- [API Endpoints](#api-endpoints)
- [Knowledge Base Schema](#knowledge-base-schema)
- [Module Descriptions](#module-descriptions)
- [Troubleshooting](#troubleshooting)

---

## Project Overview

The system implements a full adaptive prep flow:

```
PDF Document
     ↓
Section Extraction (pdfplumber)
     ↓
Check Knowledge Base → First time? Cold Start : Returning? Adaptive
     ↓
MCQ Generation via Gemini Flash API
     ↓
User Takes Exam
     ↓
Score + Explanations for Wrong Answers
     ↓
Save to SQLite Knowledge Base
     ↓
Next Visit → Weak topics injected into Gemini prompt
```

**Key requirement from spec:**
> The system must distinguish between a first-time prep run and a returning run. On returning runs, the history context (mistakes + question drift) must influence what new questions are generated.

This is fully implemented — verified by the Scenario B output files.

---

## Tech Stack

| Technology | Purpose | Why Chosen |
|------------|---------|------------|
| **Python 3.10+** | Core language | Universal, stdlib covers most needs |
| **Flask** | REST API framework | Lightweight, zero config, runs with one command |
| **SQLite** | Knowledge Base storage | Built into Python, no installation required |
| **pdfplumber** | PDF text extraction | Best accuracy for machine-readable PDFs |
| **Gemini Flash API** | MCQ generation | Free tier, 1M token context, fast JSON output |
| **click** | CLI framework | Clean command grouping, available everywhere |
| **python-dotenv** | Environment config | Keeps API key out of source code |
| **Streamlit** | Web UI | Interactive UI with zero frontend code |
| **JSON file store** | Chunk index | No extra dependencies, same interface as ChromaDB |
| **Python dataclasses** | Data models | stdlib, no pydantic required |

---

## Project Structure

```
adaptive_prep/
│
├── app/
│   ├── __init__.py         — Package marker
│   ├── config.py           — All environment variables and settings
│   ├── models.py           — Data models (MCQ, Session, KBSnapshot etc.)
│   ├── pdf_parser.py       — Extracts 10 sections from the PDF
│   ├── vector_store.py     — JSON chunk index with keyword retrieval
│   ├── database.py         — All SQLite read/write operations
│   ├── llm.py              — Gemini Flash API calls + prompt builders
│   ├── prep_engine.py      — Core orchestration (the brain)
│   └── main.py             — Flask REST API
│
├── tests/
│   └── test_system.py      — 52-test standalone suite (no pytest needed)
│
├── data/
│   ├── SLATEFALL_DOSSIER.pdf   — Source PDF (must be present)
│   ├── knowledge_base.db       — Created automatically on first run
│   └── chunk_index.json        — Created automatically by index command
│
├── outputs/
│   ├── scenario_b_iter1/
│   │   ├── questions_iter1.json
│   │   └── kb_snapshot_iter1.json
│   ├── scenario_b_iter2/
│   │   ├── questions_iter2.json
│   │   └── kb_snapshot_iter2.json
│   └── scenario_b_iter3/
│       ├── questions_iter3.json
│       └── kb_snapshot_iter3.json
│
├── cli.py                  — CLI entry point (click)
├── streamlit_app.py        — Streamlit web UI
├── requirements.txt        — Python dependencies
├── .env.example            — Environment variable template
└── README.md               — This file
```

---

## Prerequisites

- Python 3.10 or higher
- pip
- A free Gemini API key → [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

---

## Installation & Setup

### Step 1 — Extract and enter the project folder

```bash
unzip adaptive_prep.zip
cd adaptive_prep
```

> **Windows users:** Make sure you are in the correct folder.
> Run `dir` and confirm you can see `cli.py`, `app/`, `data/` etc.
> If you see another `adaptive_prep/` folder inside, `cd` into it first.

```
# Correct path — you should see these files
C:\...\adaptive_prep> dir
  app/
  data/
  tests/
  cli.py
  streamlit_app.py
  .env.example
```

---

### Step 2 — Create a virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac / Linux
python -m venv venv
source venv/bin/activate
```

You will see `(venv)` at the start of your terminal prompt when activated.

---

### Step 3 — Install dependencies

```bash
pip install flask pdfplumber click python-dotenv
```

For the Streamlit UI (optional):

```bash
pip install streamlit
```

---

### Step 4 — Configure your API key

```bash
# Windows
copy .env.example .env

# Mac / Linux
cp .env.example .env
```

Open the `.env` file and set your Gemini API key:

```
GEMINI_API_KEY=your_actual_key_here
USE_MOCK_LLM=false
```

> **No API key yet?** Set `USE_MOCK_LLM=true` to run in offline demo mode.
> Mock mode uses pre-built questions from real PDF text — no internet needed.

---

### Step 5 — Index the PDF (one-time only)

```bash
python cli.py index
```

Expected output:

```
Initialising database...
Indexing PDF...
✓ Indexed 10 chunks successfully.
```

This creates two files automatically:
- `data/knowledge_base.db` — your SQLite database
- `data/chunk_index.json` — the text chunk store

> You only need to run this once. The database and chunk index persist between runs.

---

## Running the Project

You have three options. Use whichever suits your preference.

---

### Option 1 — Streamlit Web UI (Recommended)

The easiest way. Opens in your browser with a full graphical interface.

```bash
streamlit run streamlit_app.py
```

Open your browser at: **http://localhost:8501**

**How to take an exam in the UI:**
1. Go to **🏠 Start Prep**
2. Tick the sections you want to study (§1 through §10)
3. Set number of questions per section
4. Make sure **"Demo mode" toggle is OFF** — so you answer yourself
5. Click **"Generate Questions & Start Exam"**
6. You are taken to **📝 Exam** automatically
7. Click your answer for each question (A / B / C / D)
8. Once all answered, click **"Submit & See Results"**
9. View your score and explanations in **📊 Results**
10. Check your learning history in **🗄️ Knowledge Base**

---

### Option 2 — CLI (Terminal)

Run directly from your terminal without a browser.

```bash
# Take an exam — answer yourself (interactive)
python cli.py prep "1" --no-simulate

# Multiple sections at once
python cli.py prep "1,2,3" --no-simulate

# More questions per section (default is 5)
python cli.py prep "2" --no-simulate --mcq 10

# View your score history
python cli.py snapshot

# View history for a specific section
python cli.py history "8"
```

**Interactive exam in terminal looks like this:**

```
Starting prep for sections: [1]
Mode: COLD START | Questions: 5

Q1 (Section 1 — civilian-identity):
What is SLATEFALL's civilian identity?
  A. Inez Yolanda Calvache-Renström
  B. Elena Espósito-Tagle
  C. Catalina Renström-Verdugo
  D. Claire Renström-Verdugo
Answer (A/B/C/D): A

...

SCORE: 4/5 (80.0%)
✓ Q1: Correct
✗ Q3: You chose B, correct was D
  → Explanation: Section 1 states that...
```

---

### Option 3 — Flask REST API

Start the API server and interact via HTTP requests or a tool like Postman.

```bash
python app/main.py
```

Server runs at: **http://localhost:8000**

Test it in your browser:
- http://localhost:8000/health
- http://localhost:8000/sections
- http://localhost:8000/kb/snapshot

---

## Evaluation Scenarios

### Scenario A — Cold start over any two sections

```bash
python cli.py prep "3,7" --mcq 5 --simulate
```

This runs a simulated session on sections 3 and 7 with no prior history.

---

### Scenario B — Three consecutive adaptive iterations

```bash
python cli.py scenario-b --mcq 5 --wrong-pct 0.35
```

This runs three iterations automatically and saves all output files:

| Iteration | Sections | Expected Mode |
|-----------|----------|--------------|
| Iter 1 | 5, 8 | `is_adaptive: false` — Cold Start |
| Iter 2 | 6, 8, 9 | `is_adaptive: true` — Adaptive (Section 8 has history) |
| Iter 3 | 8 | `is_adaptive: true` — Fully Adaptive (Section 8 has 2 sessions) |

Output files are saved to:

```
outputs/
├── scenario_b_iter1/
│   ├── questions_iter1.json      ← MCQs + session result
│   └── kb_snapshot_iter1.json   ← KB state at this point
├── scenario_b_iter2/
│   ├── questions_iter2.json
│   └── kb_snapshot_iter2.json
└── scenario_b_iter3/
    ├── questions_iter3.json
    └── kb_snapshot_iter3.json
```

The `is_adaptive` field in each `questions_iterN.json` is the key proof:
- Iter 1 → `"is_adaptive": false`
- Iter 2 → `"is_adaptive": true`
- Iter 3 → `"is_adaptive": true`

---

## How Adaptive Intelligence Works

### First visit (Cold Start)
No history in the database. Gemini receives a standard prompt asking for broad questions across the section.

### Return visit (Adaptive)
The system queries the database for three things before calling Gemini:

```
1. get_weak_topics()
   → Which topic_tags have the highest error rate?
   → Example: 'tail-momentum' at 100% error rate

2. get_mastered_question_ids()
   → Which questions were answered correctly 2+ times in a row?
   → These are skipped — no point drilling what you already know

3. get_previously_asked_question_ids()
   → What was asked before?
   → Passed to Gemini so it does not repeat questions
```

This context is then injected into the Gemini prompt:

```
WEAK AREAS — PRIORITIZE these topics:
  - 'tail-momentum' (error rate: 100%)
  - 'echo-lock-triggers' (error rate: 66%)

PREVIOUSLY ASKED — do NOT repeat these:
  - What is SLATEFALL's primary base?
  - How many safehouses are maintained?
```

Gemini then generates questions specifically targeting your weak areas while avoiding repetition.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/sections` | List all 10 sections with history stats |
| POST | `/prep/start` | Start a session, generate MCQs |
| POST | `/prep/submit` | Submit answers, get scored results |
| POST | `/prep/simulate` | Auto-simulate answers for a session |
| GET | `/kb/snapshot` | Top-5 recent sessions from KB |
| GET | `/kb/weak-topics` | Weak topic analysis for given sections |
| GET | `/prep/history` | Session history for given sections |

**Example — Start a session:**

```bash
curl -X POST http://localhost:8000/prep/start \
  -H "Content-Type: application/json" \
  -d '{"section_ids": [1, 2], "mcq_per_section": 5}'
```

---

## Knowledge Base Schema

The SQLite database (`data/knowledge_base.db`) has four tables:

```sql
sessions
  session_id    TEXT PRIMARY KEY
  timestamp     TEXT
  total_q       INTEGER
  correct_count INTEGER
  wrong_count   INTEGER
  score_pct     REAL
  sections_json TEXT         -- JSON array e.g. [5, 8]

session_sections             -- which sections each session covered
  session_id    TEXT
  section_id    INTEGER

questions                    -- MCQ definitions (reused across sessions)
  question_id   TEXT PRIMARY KEY
  section_id    INTEGER
  question_text TEXT
  choices_json  TEXT
  correct_label TEXT
  explanation   TEXT
  topic_tag     TEXT         -- used for weak topic detection
  created_at    TEXT

question_results             -- per-session, per-question outcome
  session_id    TEXT
  question_id   TEXT
  section_id    INTEGER
  user_label    TEXT         -- what the user answered
  is_correct    INTEGER      -- 0 or 1
  timestamp     TEXT
```

---

## Module Descriptions

| Module | Role |
|--------|------|
| `config.py` | Loads all env vars, defines section titles and valid section IDs |
| `models.py` | Dataclasses for MCQ, SessionResult, KBSnapshot, UserAnswer etc. |
| `pdf_parser.py` | Opens PDF with pdfplumber, detects "Section N." markers, extracts text for each of the 10 sections |
| `vector_store.py` | Splits section text into chunks, saves to JSON, retrieves relevant chunks via keyword scoring |
| `database.py` | All SQLite operations — save sessions, query weak topics, detect mastered questions, generate KB snapshots |
| `llm.py` | Builds cold-start or adaptive prompts, calls Gemini Flash via urllib HTTP, parses JSON response into MCQ objects |
| `prep_engine.py` | Orchestrates the full prep flow — checks history, calls LLM, scores answers, saves to DB |
| `main.py` | Flask REST API with all endpoints |
| `cli.py` | Click CLI — index, prep, scenario-b, snapshot, history commands |
| `streamlit_app.py` | 4-page Streamlit UI — Start Prep, Exam, Results, Knowledge Base |
| `tests/test_system.py` | 52 tests covering DB, PDF parser, scoring, LLM, prep engine, and Scenario B |

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'app'`**
You are in the wrong directory. Run `dir` (Windows) or `ls` (Mac/Linux) and make sure you can see `cli.py` and the `app/` folder. If not, `cd` to the correct folder.

**`HTTP Error 404: Not Found` from Gemini**
Your Gemini model name may be outdated. Open `app/config.py` and change:
```python
GEMINI_MODEL: str = "gemini-2.0-flash"
```

**`GEMINI_API_KEY not set`**
Open your `.env` file and make sure the key is set correctly with no quotes or spaces:
```
GEMINI_API_KEY=AIzaSyXXXXXXXXXXXXXXXX
```

**`FontBBox WARNING` messages**
These are harmless warnings from pdfplumber about a font in the PDF. Text extraction works correctly despite them. Ignore these messages.

**`venv\Scripts\activate` not working on Windows PowerShell**
Run this first to allow script execution:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```
Then activate:
```powershell
venv\Scripts\activate
```

**Database not found / empty**
You have not indexed the PDF yet. Run:
```bash
python cli.py index
```

---

## Running Tests

No external test framework required. Run directly with Python:

```bash
python tests/test_system.py
```

Expected output:
```
── Database Tests ──
  ✓ DB init creates all required tables
  ✓ Save question and retrieve by question_id
  ... (52 tests total)

============================================================
Results: 52/52 passed, 0 failed
All tests passed! ✓
```

---

## Quick Reference

```bash
# First time setup
python -m venv venv
venv\Scripts\activate          # Windows
pip install flask pdfplumber click python-dotenv
cp .env.example .env           # add your GEMINI_API_KEY
python cli.py index

# Daily use
python cli.py prep "1,2" --no-simulate        # CLI exam
streamlit run streamlit_app.py                # Web UI
python app/main.py                            # API server

# Evaluation
python cli.py scenario-b                      # Scenario B (3 iterations)
python tests/test_system.py                   # Run all 52 tests
python cli.py snapshot                        # View KB history
```
