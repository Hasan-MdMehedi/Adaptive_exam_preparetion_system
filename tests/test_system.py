"""
Tests :Adaptive Document Preparation Syste
Self-contained test runner (no external test framework needed).
Run with: python3 tests/test_system.py
"""
import sys, os, uuid, json, tempfile, importlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["USE_MOCK_LLM"] = "true"

PASSED = []
FAILED = []


def test(name):
    """Decorator that registers and runs a test function."""
    def decorator(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"  ✓ {name}")
        except AssertionError as e:
            FAILED.append((name, f"AssertionError: {e}"))
            print(f"  ✗ {name}: AssertionError: {e}")
        except Exception as e:
            import traceback
            FAILED.append((name, str(e)))
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    return decorator


#Helpers

from app.models import MCQ, MCQChoice, UserAnswer, QuestionResult, SessionResult
from app.database import (init_db, save_questions, save_session,
    has_prior_history, get_weak_topics, get_mastered_question_ids,
    get_sessions_for_sections, get_kb_snapshot)
from app.pdf_parser import chunk_section, get_section_text


def fresh_db():
    """Create an isolated SQLite DB in a temp dir."""
    d = Path(tempfile.mkdtemp())
    db = d / "test.db"
    init_db(db)
    return db


def make_mcq(section_id=1, topic="test-topic"):
    return MCQ(
        question_id=str(uuid.uuid4()), section_id=section_id,
        question="What is SLATEFALL's primary power?",
        choices=[MCQChoice("A","Inertial Suspension"), MCQChoice("B","Telekinesis"),
                 MCQChoice("C","Flight"), MCQChoice("D","Invisibility")],
        correct_label="A", explanation="Section 2 confirms Inertial Suspension.",
        topic_tag=topic)


def make_session(session_id, section_ids, mcqs, wrong_indices=None):
    wrong_indices = wrong_indices or []
    results = []
    for i, q in enumerate(mcqs):
        is_correct = i not in wrong_indices
        results.append(QuestionResult(
            question_id=q.question_id, section_id=q.section_id,
            question=q.question, choices=q.choices,
            correct_label=q.correct_label,
            user_label=q.correct_label if is_correct else "B",
            is_correct=is_correct, explanation=q.explanation,
            topic_tag=q.topic_tag))
    correct = sum(1 for r in results if r.is_correct)
    total = len(results)
    return SessionResult(
        session_id=session_id, sections=section_ids,
        timestamp="2026-01-01T00:00:00+00:00", total_questions=total,
        correct_count=correct, wrong_count=total - correct,
        score_pct=round(correct * 100 / total, 2) if total else 0.0,
        results=results)


# Database Tests

print("\n── Database Tests ──")

@test("DB init creates all required tables")
def _():
    import sqlite3
    db = fresh_db()
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert {"sessions","session_sections","questions","question_results"} <= tables

@test("Save question and retrieve by question_id")
def _():
    import sqlite3
    db = fresh_db()
    q = make_mcq(section_id=2)
    save_questions([q], db_path=db)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT section_id FROM questions WHERE question_id=?",
                       (q.question_id,)).fetchone()
    conn.close()
    assert row is not None and row[0] == 2

@test("No prior history on empty DB")
def _():
    db = fresh_db()
    assert not has_prior_history([1, 2, 3], db_path=db)

@test("Prior history detected after saving a session")
def _():
    db = fresh_db()
    q = make_mcq(section_id=5)
    save_questions([q], db_path=db)
    save_session(make_session(str(uuid.uuid4()), [5], [q], wrong_indices=[0]), db_path=db)
    assert has_prior_history([5], db_path=db)

@test("Untouched section has no history")
def _():
    db = fresh_db()
    q = make_mcq(section_id=5)
    save_questions([q], db_path=db)
    save_session(make_session(str(uuid.uuid4()), [5], [q]), db_path=db)
    assert not has_prior_history([9], db_path=db)

@test("Weak topic detection with 100% error rate")
def _():
    db = fresh_db()
    q = make_mcq(section_id=5, topic="sequential-suspension")
    save_questions([q], db_path=db)
    save_session(make_session(str(uuid.uuid4()), [5], [q], wrong_indices=[0]), db_path=db)
    weak = get_weak_topics([5], db_path=db)
    assert len(weak) == 1
    assert weak[0]["topic_tag"] == "sequential-suspension"
    assert weak[0]["error_rate"] == 100.0

@test("No weak topics when all correct")
def _():
    db = fresh_db()
    q = make_mcq(section_id=3, topic="inertial-basics")
    save_questions([q], db_path=db)
    save_session(make_session(str(uuid.uuid4()), [3], [q], wrong_indices=[]), db_path=db)
    weak = get_weak_topics([3], db_path=db)
    assert len(weak) == 0

@test("Mastered question: 2 consecutive correct answers")
def _():
    db = fresh_db()
    q = make_mcq(section_id=3)
    save_questions([q], db_path=db)
    for _ in range(2):
        s = make_session(str(uuid.uuid4()), [3], [q], wrong_indices=[])
        save_session(s, db_path=db)
    mastered = get_mastered_question_ids([3], min_correct_streak=2, db_path=db)
    assert q.question_id in mastered

@test("Not mastered if last attempt was wrong (streak broken)")
def _():
    db = fresh_db()
    q = make_mcq(section_id=3)
    save_questions([q], db_path=db)
    # Correct first, then wrong — streak broken
    save_session(make_session(str(uuid.uuid4()), [3], [q], wrong_indices=[]), db_path=db)
    save_session(make_session(str(uuid.uuid4()), [3], [q], wrong_indices=[0]), db_path=db)
    mastered = get_mastered_question_ids([3], min_correct_streak=2, db_path=db)
    assert q.question_id not in mastered

@test("KB snapshot has correct structure and session count")
def _():
    db = fresh_db()
    q = make_mcq(section_id=1)
    save_questions([q], db_path=db)
    save_session(make_session(str(uuid.uuid4()), [1], [q]), db_path=db)
    snap = get_kb_snapshot(top_n=5, db_path=db)
    assert snap.sessions_shown == 1
    assert snap.records[0].total_questions == 1

@test("KB snapshot respects top_n limit")
def _():
    db = fresh_db()
    for _ in range(7):
        q = make_mcq()
        save_questions([q], db_path=db)
        save_session(make_session(str(uuid.uuid4()), [1], [q]), db_path=db)
    snap = get_kb_snapshot(top_n=5, db_path=db)
    assert snap.sessions_shown == 5

@test("Duplicate question_id is ignored (INSERT OR IGNORE)")
def _():
    import sqlite3
    db = fresh_db()
    q = make_mcq()
    save_questions([q], db_path=db)
    save_questions([q], db_path=db)  # Should not raise or duplicate
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    assert count == 1

@test("Session sections correctly linked via session_sections table")
def _():
    import sqlite3
    db = fresh_db()
    q = make_mcq(section_id=7)
    save_questions([q], db_path=db)
    sid = str(uuid.uuid4())
    save_session(make_session(sid, [7], [q]), db_path=db)
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT section_id FROM session_sections WHERE session_id=?", (sid,)).fetchall()
    conn.close()
    assert [r[0] for r in rows] == [7]

@test("get_sessions_for_sections returns correct sessions")
def _():
    db = fresh_db()
    q = make_mcq(section_id=6)
    save_questions([q], db_path=db)
    sid = str(uuid.uuid4())
    save_session(make_session(sid, [6], [q]), db_path=db)
    sessions = get_sessions_for_sections([6], db_path=db)
    assert len(sessions) == 1 and sessions[0]["session_id"] == sid


# PDF Parser Tests

print("\n── PDF Parser Tests ──")

@test("Chunk single paragraph returns one chunk")
def _():
    chunks = chunk_section("A single paragraph of text here.", chunk_size=200)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) and c for c in chunks)

@test("Chunk splits text at paragraph boundaries")
def _():
    text = "Para A.\n\nPara B.\n\nPara C.\n\nPara D.\n\nPara E."
    chunks = chunk_section(text, chunk_size=15)  # force splits
    assert len(chunks) >= 2

@test("Chunk preserves all content across splits")
def _():
    text = "Alpha fact.\n\nBeta fact.\n\nGamma fact."
    chunks = chunk_section(text, chunk_size=100)
    combined = " ".join(chunks)
    assert "Alpha fact" in combined and "Beta fact" in combined

@test("PDF section 1 extracted with content")
def _():
    text = get_section_text(1)
    assert len(text) > 500
    assert "SLATEFALL" in text or "Identity" in text or "Calvache" in text

@test("PDF section 2 contains powers information")
def _():
    text = get_section_text(2)
    assert "Inertial" in text or "Suspension" in text or "power" in text.lower()

@test("PDF section 5 contains tactics")
def _():
    text = get_section_text(5)
    assert "Doctrine" in text or "Suspension" in text or "tactical" in text.lower()

@test("PDF section 8 contains bases/safehouses")
def _():
    text = get_section_text(8)
    assert "Valparaíso" in text or "safehouse" in text.lower() or "base" in text.lower()

@test("All 10 sections parseable and non-empty")
def _():
    from app.pdf_parser import extract_sections
    secs = extract_sections()
    assert len(secs) == 10
    for sid, txt in secs.items():
        assert len(txt) > 100, f"Section {sid} too short: {len(txt)} chars"


#Scoring Tests 

print("\n── Scoring Tests ──")

@test("Perfect score: all correct")
def _():
    qs = [make_mcq() for _ in range(4)]
    s = make_session(str(uuid.uuid4()), [1], qs, wrong_indices=[])
    assert s.correct_count == 4 and s.wrong_count == 0 and s.score_pct == 100.0

@test("Zero score: all wrong")
def _():
    qs = [make_mcq() for _ in range(4)]
    s = make_session(str(uuid.uuid4()), [1], qs, wrong_indices=[0,1,2,3])
    assert s.correct_count == 0 and s.wrong_count == 4 and s.score_pct == 0.0

@test("Partial score 50%: 2 of 4 correct")
def _():
    qs = [make_mcq() for _ in range(4)]
    s = make_session(str(uuid.uuid4()), [1], qs, wrong_indices=[0, 1])
    assert s.correct_count == 2 and s.score_pct == 50.0

@test("Partial score 75%: 3 of 4 correct")
def _():
    qs = [make_mcq() for _ in range(4)]
    s = make_session(str(uuid.uuid4()), [1], qs, wrong_indices=[0])
    assert s.correct_count == 3 and round(s.score_pct, 1) == 75.0

@test("Wrong answers appear in results with correct is_correct=False")
def _():
    qs = [make_mcq() for _ in range(2)]
    s = make_session(str(uuid.uuid4()), [1], qs, wrong_indices=[1])
    assert s.results[0].is_correct is True
    assert s.results[1].is_correct is False
    assert s.results[1].user_label == "B"
    assert s.results[1].correct_label == "A"


# LLM / MCQ Generation Tests

print("\n── LLM / MCQ Generation Tests ──")

@test("Mock MCQ generation returns requested count")
def _():
    from app.llm import generate_mcqs
    qs = generate_mcqs(section_id=5, section_text="Sample text about tactics.", n_questions=3)
    assert len(qs) == 3

@test("Mock MCQs have 4 choices each")
def _():
    from app.llm import generate_mcqs
    qs = generate_mcqs(section_id=2, section_text="Inertial Suspension details.", n_questions=5)
    for q in qs:
        assert len(q.choices) == 4, f"Expected 4 choices, got {len(q.choices)}"

@test("Mock MCQ correct_label is always A, B, C, or D")
def _():
    from app.llm import generate_mcqs
    qs = generate_mcqs(section_id=7, section_text="Adversary details.", n_questions=4)
    for q in qs:
        assert q.correct_label in ("A","B","C","D")

@test("Mock MCQs have non-empty topic_tag")
def _():
    from app.llm import generate_mcqs
    qs = generate_mcqs(section_id=6, section_text="Allies section.", n_questions=3)
    for q in qs:
        assert q.topic_tag, "topic_tag should be non-empty"

@test("Mock MCQs have unique question_ids")
def _():
    from app.llm import generate_mcqs
    qs = generate_mcqs(section_id=9, section_text="Case files.", n_questions=5)
    ids = [q.question_id for q in qs]
    assert len(ids) == len(set(ids)), "question_ids must be unique"

@test("Adaptive prompt path is triggered when weak topics present")
def _():
    from app.llm import _build_adaptive_prompt, _build_cold_start_prompt
    weak = [{"topic_tag": "tail-momentum", "error_rate": 80.0}]
    prompt = _build_adaptive_prompt(5, "Section text", 3, weak, [])
    assert "tail-momentum" in prompt
    assert "WEAK AREAS" in prompt

@test("Cold-start prompt does not contain adaptive language")
def _():
    from app.llm import _build_cold_start_prompt
    prompt = _build_cold_start_prompt(5, "Section text", 3)
    assert "WEAK AREAS" not in prompt
    assert "PREVIOUSLY ASKED" not in prompt


#Prep Engine Integration Tests

print("\n── Prep Engine Integration Tests ──")

@test("Cold-start session: is_returning=False on fresh DB")
def _():
    import app.database as db_mod
    db = fresh_db()
    orig = db_mod.DB_PATH
    db_mod.DB_PATH = db
    try:
        from app.prep_engine import start_prep_session
        prep = start_prep_session([2], mcq_per_section=3)
        assert not prep.is_returning, "First-ever run must be cold-start"
    finally:
        db_mod.DB_PATH = orig

@test("Returning session: is_returning=True after prior session")
def _():
    import app.database as db_mod
    db = fresh_db()
    orig = db_mod.DB_PATH
    db_mod.DB_PATH = db
    try:
        from app.prep_engine import start_prep_session, submit_answers, simulate_answers
        prep1 = start_prep_session([4], mcq_per_section=3)
        submit_answers(prep1.session_id, simulate_answers(prep1.questions, 0.5))
        prep2 = start_prep_session([4], mcq_per_section=3)
        assert prep2.is_returning, "Second run must be adaptive/returning"
    finally:
        db_mod.DB_PATH = orig

@test("Full round-trip: start → simulate → submit → scored result")
def _():
    import app.database as db_mod
    db = fresh_db()
    orig = db_mod.DB_PATH
    db_mod.DB_PATH = db
    try:
        from app.prep_engine import start_prep_session, submit_answers, simulate_answers
        prep = start_prep_session([1], mcq_per_section=4)
        assert len(prep.questions) == 4
        answers = simulate_answers(prep.questions, wrong_pct=0.25)
        result = submit_answers(prep.session_id, answers)
        sr = result.session_result
        assert sr.total_questions == 4
        assert sr.correct_count + sr.wrong_count == 4
        assert 0.0 <= sr.score_pct <= 100.0
    finally:
        db_mod.DB_PATH = orig

@test("Submit to unknown session raises KeyError")
def _():
    from app.prep_engine import submit_answers
    try:
        submit_answers("ghost-session-id", [])
        assert False, "Should have raised KeyError"
    except KeyError:
        pass

@test("simulate_answers produces correct proportion of wrong answers")
def _():
    from app.prep_engine import simulate_answers
    qs = [make_mcq() for _ in range(200)]
    answers = simulate_answers(qs, wrong_pct=0.4)
    wrong = sum(1 for a, q in zip(answers, qs) if a.chosen_label != q.correct_label)
    # Allow ±15% statistical tolerance
    assert 50 <= wrong <= 110, f"Expected ~80 wrong (40% of 200), got {wrong}"

@test("simulate_answers produces all correct when wrong_pct=0.0")
def _():
    from app.prep_engine import simulate_answers
    qs = [make_mcq() for _ in range(10)]
    answers = simulate_answers(qs, wrong_pct=0.0)
    wrong = sum(1 for a, q in zip(answers, qs) if a.chosen_label != q.correct_label)
    assert wrong == 0

@test("simulate_answers produces all wrong when wrong_pct=1.0")
def _():
    from app.prep_engine import simulate_answers
    qs = [make_mcq() for _ in range(10)]
    answers = simulate_answers(qs, wrong_pct=1.0)
    wrong = sum(1 for a, q in zip(answers, qs) if a.chosen_label != q.correct_label)
    assert wrong == 10

@test("Session persisted to KB after submit")
def _():
    # Uses real global DB — count sessions before and after for section 10 (untouched by Scenario B)
    from app.prep_engine import start_prep_session, submit_answers, simulate_answers
    before = len(get_sessions_for_sections([10]))
    prep = start_prep_session([10], mcq_per_section=2)
    submit_answers(prep.session_id, simulate_answers(prep.questions, 0.5))
    after = len(get_sessions_for_sections([10]))
    assert after == before + 1, f"Expected {before+1} sessions, got {after}"

@test("Multi-section session covers all requested sections")
def _():
    import app.database as db_mod
    db = fresh_db()
    orig = db_mod.DB_PATH
    db_mod.DB_PATH = db
    try:
        from app.prep_engine import start_prep_session, submit_answers, simulate_answers
        prep = start_prep_session([1, 3], mcq_per_section=2)
        # Should have questions from both sections
        section_ids = {q.section_id for q in prep.questions}
        assert 1 in section_ids and 3 in section_ids
    finally:
        db_mod.DB_PATH = orig


# Vector Store Tests

print("\n── Vector Store Tests ──")

@test("Index creates chunk file on disk")
def _():
    import tempfile, app.vector_store as vs_mod
    d = Path(tempfile.mkdtemp())
    orig = vs_mod.INDEX_FILE
    vs_mod.INDEX_FILE = d / "chunk_index.json"
    vs_mod._load_index.cache_clear()
    try:
        count = vs_mod.index_pdf(force=True)
        assert count > 0
        assert vs_mod.INDEX_FILE.exists()
    finally:
        vs_mod.INDEX_FILE = orig
        vs_mod._load_index.cache_clear()

@test("retrieve_chunks returns strings for valid section")
def _():
    from app.vector_store import retrieve_chunks, index_pdf
    index_pdf()  # ensure indexed
    chunks = retrieve_chunks(section_id=5, n_results=3)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) and c for c in chunks)

@test("retrieve_chunks with query returns relevant text")
def _():
    from app.vector_store import retrieve_chunks
    chunks = retrieve_chunks(section_id=2, query="Inertial Suspension mass ceiling", n_results=3)
    assert len(chunks) >= 1

@test("get_indexed_sections returns all 10 section IDs")
def _():
    from app.vector_store import get_indexed_sections, index_pdf
    index_pdf()
    sections = get_indexed_sections()
    assert len(sections) == 10
    assert set(sections) == set(range(1, 11))


# Model Serialization Tests 

print("\n── Model Serialization Tests ──")

@test("MCQ.model_dump() produces valid dict")
def _():
    q = make_mcq()
    d = q.model_dump()
    assert isinstance(d, dict)
    assert "question_id" in d and "choices" in d and "correct_label" in d

@test("SessionResult.model_dump() is JSON-serializable")
def _():
    qs = [make_mcq()]
    s = make_session(str(uuid.uuid4()), [1], qs)
    d = s.model_dump()
    dumped = json.dumps(d)  # must not raise
    assert isinstance(dumped, str) and len(dumped) > 10

@test("KBSnapshot.model_dump() is JSON-serializable")
def _():
    db = fresh_db()
    q = make_mcq()
    save_questions([q], db_path=db)
    save_session(make_session(str(uuid.uuid4()), [1], [q]), db_path=db)
    snap = get_kb_snapshot(top_n=5, db_path=db)
    dumped = json.dumps(snap.model_dump())
    assert isinstance(dumped, str) and "session_id" in dumped


#Scenario B Smoke Test 

print("\n── Scenario B Smoke Test ──")

@test("Scenario B: adaptive mode verified from real KB history")
def _():
    # Scenario B already ran — sections 5,6,8,9 have history; verify adaptive is triggered
    from app.prep_engine import start_prep_session, submit_answers, simulate_answers
    from app.database import has_prior_history
    # Sections from Scenario B must be marked as returning
    assert has_prior_history([8]), "Section 8 must have prior Scenario B history"
    assert has_prior_history([5]), "Section 5 must have prior Scenario B history"
    # Start a new session for section 8 — it MUST be adaptive
    prep = start_prep_session([8], mcq_per_section=2)
    assert prep.is_returning, "Section 8 must trigger adaptive mode after Scenario B"
    submit_answers(prep.session_id, simulate_answers(prep.questions, 0.4))

@test("Scenario B: output files exist and have correct structure")
def _():
    import json
    from pathlib import Path as P
    for i in range(1, 4):
        qf = P(f"outputs/scenario_b_iter{i}/questions_iter{i}.json")
        sf = P(f"outputs/scenario_b_iter{i}/kb_snapshot_iter{i}.json")
        assert qf.exists(), f"Missing: {qf}"
        assert sf.exists(), f"Missing: {sf}"
        q_data = json.loads(qf.read_text())
        assert "questions" in q_data and len(q_data["questions"]) > 0
        assert q_data["iteration"] == i
        assert "session_result" in q_data
        s_data = json.loads(sf.read_text())
        assert "records" in s_data and "snapshot_taken_at" in s_data
        assert s_data["iteration"] == i


# Summary

total = len(PASSED) + len(FAILED)
print(f"\n{'='*60}")
print(f"Results: {len(PASSED)}/{total} passed, {len(FAILED)} failed")
if FAILED:
    print("\nFailed tests:")
    for name, err in FAILED:
        print(f"  ✗ {name}")
        print(f"    {err}")
    sys.exit(1)
else:
    print("All tests passed! ✓")
    sys.exit(0)

