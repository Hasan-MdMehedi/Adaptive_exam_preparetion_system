"""
Flask REST API — Adaptive Document Preparation Syste
Endpoints:
  POST /prep/start          — generate MCQs (adaptive if returning)
  POST /prep/submit         — score answers, persist to KB
  POST /prep/simulate       — auto-simulate + submit for a session
  GET  /prep/history        — session history for sections
  GET  /kb/snapshot         — top-5 KB sessions
  GET  /kb/weak-topics      — weak topic analysis
  GET  /sections            — list all 10 sections
  GET  /health              — health check
"""

import json
import logging
from flask import Flask, request, jsonify

from app.config import VALID_SECTIONS, SECTION_TITLES
from app.database import (
    init_db, get_sessions_for_sections, get_kb_snapshot,
    get_weak_topics, get_section_stats,
)
from app.prep_engine import (
    start_prep_session, submit_answers, simulate_answers,
    _active_sessions,
)
from app.models import UserAnswer
from app.vector_store import index_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize on import
init_db()
try:
    index_pdf()
except Exception as e:
    logger.warning(f"PDF indexing skipped: {e}")


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# Health

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "adaptive-prep"})


# Sections

@app.get("/sections")
def list_sections():
    result = []
    for sid in VALID_SECTIONS:
        stats = get_section_stats([sid])
        result.append({
            "section_id": sid,
            "title": SECTION_TITLES[sid],
            "has_history": stats["sessions"] > 0,
            "past_sessions": stats["sessions"],
            "average_score_pct": stats["avg_score_pct"],
        })
    return jsonify(result)


# Prep Flow

@app.post("/prep/start")
def prep_start():
    body = request.get_json(force=True)
    section_ids = body.get("section_ids", [])
    if not section_ids:
        return _err("section_ids is required and must be non-empty")
    invalid = [s for s in section_ids if s not in VALID_SECTIONS]
    if invalid:
        return _err(f"Invalid section IDs: {invalid}. Valid range: 1–10.")
    try:
        resp = start_prep_session(
            section_ids=section_ids,
            mcq_per_section=body.get("mcq_per_section"),
        )
        return jsonify({
            "session_id": resp.session_id,
            "sections": resp.sections,
            "is_returning": resp.is_returning,
            "total_questions": len(resp.questions),
            "questions": [q.model_dump() for q in resp.questions],
        })
    except EnvironmentError as e:
        return _err(str(e), 503)
    except RuntimeError as e:
        return _err(str(e), 500)


@app.post("/prep/submit")
def prep_submit():
    body = request.get_json(force=True)
    session_id = body.get("session_id")
    answers_raw = body.get("answers", [])
    if not session_id:
        return _err("session_id is required")
    answers = [UserAnswer(**a) for a in answers_raw]
    try:
        resp = submit_answers(session_id, answers)
        return jsonify(resp.session_result.model_dump())
    except KeyError as e:
        return _err(str(e), 404)


@app.post("/prep/simulate")
def prep_simulate():
    session_id = request.args.get("session_id")
    wrong_pct = float(request.args.get("wrong_pct", 0.35))
    if not session_id or session_id not in _active_sessions:
        return _err(f"Session '{session_id}' not found.", 404)
    questions = _active_sessions[session_id]
    answers = simulate_answers(questions, wrong_pct=wrong_pct)
    try:
        resp = submit_answers(session_id, answers)
        return jsonify(resp.session_result.model_dump())
    except KeyError as e:
        return _err(str(e), 404)


# Knowledge Base

@app.get("/kb/snapshot")
def kb_snapshot():
    top_n = int(request.args.get("top_n", 5))
    snap = get_kb_snapshot(top_n=top_n)
    return jsonify(snap.model_dump())


@app.get("/kb/weak-topics")
def kb_weak_topics():
    raw = request.args.get("section_ids", "")
    try:
        ids = [int(s.strip()) for s in raw.split(",") if s.strip()]
    except ValueError:
        return _err("section_ids must be comma-separated integers")
    if not ids:
        return _err("section_ids is required")
    top_n = int(request.args.get("top_n", 10))
    return jsonify(get_weak_topics(ids, top_n=top_n))


@app.get("/prep/history")
def prep_history():
    raw = request.args.get("section_ids", "")
    try:
        ids = [int(s.strip()) for s in raw.split(",") if s.strip()]
    except ValueError:
        return _err("section_ids must be comma-separated integers")
    sessions = get_sessions_for_sections(ids)
    return jsonify({"section_ids": ids, "session_count": len(sessions), "sessions": sessions})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8000)