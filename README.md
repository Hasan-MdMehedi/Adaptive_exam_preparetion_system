# Adaptive Document Preparation System

An AI-powered adaptive study tool that ingests a multi-section PDF, generates MCQs using an LLM, collects user answers, scores them, persists a Knowledge Base of each session and adapts future question sets based on historical weak areas.

---

## Prerequisites

- Python 3.10+
- A free Gemini API key → [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

---

## Setup

```bash
# 1. Enter project folder
cd adaptive_prep

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Mac/Linux

# 3. Install dependencies
pip install flask pdfplumber click python-dotenv

# 4. Configure API key
copy .env.example .env         # Windows
cp .env.example .env           # Mac/Linux
# Open .env and set: GEMINI_API_KEY=your_key_here

# 5. Index the PDF (one-time)
python cli.py index
```

> No API key? Add `USE_MOCK_LLM=true` to `.env` for offline demo mode.

---

## Stack Choices & Reasoning

| Component | Choice | Reason |
|-----------|--------|--------|
| Backend | Flask | Lightweight, zero config, runs with one command |
| LLM | Gemini Flash (free) | Free tier, 1M token context, fast JSON output |
| PDF Parsing | pdfplumber | Best accuracy for machine-readable PDFs |
| Knowledge Base | SQLite | Built into Python, no installation required |
| Vector Store | JSON chunk index | No extra dependencies, same interface as ChromaDB |
| CLI | click | Clean command grouping, self-documenting |
| UI | Streamlit | Interactive UI with zero frontend code |

---

## Running the System

### CLI

```bash
# Exam
python cli.py prep "1,2" --simulate

# View Knowledge Base history
python cli.py snapshot

# View history for a specific section
python cli.py history "8"
```

### Streamlit UI

```bash
pip install streamlit
streamlit run streamlit_app.py
# Opens at http://localhost:8501
Give Exam through UI.
```

### Flask REST API

```bash
 python -m app.main
# Runs at http://localhost:8000
```

Key endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sections` | List all 10 sections with history stats |
| POST | `/prep/start` | Start a session, generate MCQs |
| POST | `/prep/submit` | Submit answers, get scored results |
| GET | `/kb/snapshot` | Top-5 recent sessions from KB |
| GET | `/kb/weak-topics` | Weak topic analysis for given sections |

---

## Evaluation Scenarios

### Scenario A — Cold start over any two sections

```bash
python cli.py prep "3,7" --mcq 5 --simulate
```

### Scenario B — Three consecutive adaptive iterations

```bash
python cli.py scenario-b --mcq 5 --wrong-pct 0.35
```

Runs three iterations automatically:

| Iteration | Sections | Mode |
|-----------|----------|------|
| Iter 1 | 5, 8 | `is_adaptive: false` — Cold Start |
| Iter 2 | 6, 8, 9 | `is_adaptive: true` — Adaptive |
| Iter 3 | 8 | `is_adaptive: true` — Fully Adaptive |

Outputs saved to:

```
outputs/
├── scenario_b_iter1/
│   ├── questions_iter1.json
│   └── kb_snapshot_iter1.json
├── scenario_b_iter2/
│   ├── questions_iter2.json
│   └── kb_snapshot_iter2.json
└── scenario_b_iter3/
    ├── questions_iter3.json
    └── kb_snapshot_iter3.json
```

---

## Knowledge Base Design

SQLite database at `data/knowledge_base.db` with four tables:

```sql
sessions          — one row per completed prep session
session_sections  — which sections were covered in each session
questions         — MCQ definitions (reused across sessions)
question_results  — per-session, per-question user answer + outcome
```

**Key query patterns:**

| Purpose | Query pattern |
|---------|--------------|
| Prior sessions for sections | JOIN sessions + session_sections WHERE section_id IN (...) |
| Weak topics | GROUP BY topic_tag ORDER BY error_rate DESC |
| Mastered questions | Last N attempts all correct via window function |
| KB snapshot | SELECT sessions ORDER BY timestamp DESC LIMIT 5 |

---

## Retrieval & Adaptive Intelligence

### First visit (Cold Start)
No history in DB. Gemini receives a standard prompt for broad questions.

### Return visit (Adaptive)
System queries DB for three things before calling Gemini:

1. `get_weak_topics()` — topic tags with highest error rate
2. `get_mastered_question_ids()` — questions answered correctly 2+ times in a row
3. `get_previously_asked_question_ids()` — questions to avoid repeating

This context is injected into the Gemini prompt:

```
WEAK AREAS — PRIORITIZE these topics:
  - 'tail-momentum' (error rate: 100%)
  - 'echo-lock-triggers' (error rate: 66%)

PREVIOUSLY ASKED — do NOT repeat these:
  - What is SLATEFALL's primary base?
```

---

## Running Tests

```bash
python tests/test_system.py
```

52 tests covering: DB CRUD, PDF parsing, scoring, MCQ generation, prep engine flow, and Scenario B output validation. No external framework required.

---

## Known Limitations

- In-memory session state: active sessions are stored in process memory. Restarting the server loses open sessions.
- Simulated answers: Scenario B uses `wrong_pct=0.35` to demonstrate adaptive behaviour.
- Vector store uses keyword overlap scoring instead of semantic embeddings. To upgrade to ChromaDB, swap `app/vector_store.py` — the interface is identical.
- `FontBBox WARNING` from pdfplumber is harmless — text extraction is not affected.

---

## Section Mapping

| ID | Title |
|----|-------|
| 1 | Identity, Background, and Public Status |
| 2 | Powers, Abilities, and Documented Limits |
| 3 | Origin and Key Historical Events |
| 4 | Equipment, Gear, and Specialized Technology |
| 5 | Operational Tactics and Combat Doctrine |
| 6 | Allies, Networks, and Known Affiliations |
| 7 | Adversaries and Documented Threats |
| 8 | Known Bases, Safehouses, and Operational Territory |
| 9 | Case Files: Documented Engagements and Incidents |
| 10 | Glossary, Codenames, and Reference Tables |
