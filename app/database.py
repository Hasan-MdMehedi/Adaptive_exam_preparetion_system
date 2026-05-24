"""
Knowledge Base — SQLite Layer

Schema:
  sessions          — one row per prep session
  session_sections  — which sections were studied in each session
  questions         — MCQ definitions (reused across sessions)
  question_results  — per-session, per-question user answer + outcome
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

from app.config import DB_PATH
from app.models import (
    MCQ, QuestionResult, SessionResult, KBSnapshot, KBSnapshotRecord
)

logger = logging.getLogger(__name__)


def _get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db(db_path: Path = DB_PATH):
    conn = _get_conn(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with get_db(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id    TEXT PRIMARY KEY,
                timestamp     TEXT NOT NULL,
                total_q       INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_count   INTEGER NOT NULL DEFAULT 0,
                score_pct     REAL NOT NULL DEFAULT 0.0,
                sections_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS session_sections (
                session_id  TEXT NOT NULL REFERENCES sessions(session_id),
                section_id  INTEGER NOT NULL,
                PRIMARY KEY (session_id, section_id)
            );

            CREATE TABLE IF NOT EXISTS questions (
                question_id   TEXT PRIMARY KEY,
                section_id    INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                choices_json  TEXT NOT NULL,
                correct_label TEXT NOT NULL,
                explanation   TEXT NOT NULL,
                topic_tag     TEXT NOT NULL DEFAULT '',
                source_chunk  TEXT NOT NULL DEFAULT '',
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS question_results (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT NOT NULL REFERENCES sessions(session_id),
                question_id   TEXT NOT NULL REFERENCES questions(question_id),
                section_id    INTEGER NOT NULL,
                user_label    TEXT NOT NULL,
                is_correct    INTEGER NOT NULL,  -- 0 or 1
                timestamp     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_qr_session   ON question_results(session_id);
            CREATE INDEX IF NOT EXISTS idx_qr_question  ON question_results(question_id);
            CREATE INDEX IF NOT EXISTS idx_qr_section   ON question_results(section_id);
            CREATE INDEX IF NOT EXISTS idx_ss_section   ON session_sections(section_id);
        """)
    logger.info(f"Database initialised at {db_path}")


#  Write Operations

def save_questions(questions: list[MCQ], db_path: Path = DB_PATH) -> None:
    """Persist MCQ definitions. Ignores duplicates (same question_id)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO questions
              (question_id, section_id, question_text, choices_json,
               correct_label, explanation, topic_tag, source_chunk, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    q.question_id,
                    q.section_id,
                    q.question,
                    json.dumps([c.model_dump() for c in q.choices]),
                    q.correct_label,
                    q.explanation,
                    q.topic_tag,
                    q.source_chunk,
                    now,
                )
                for q in questions
            ],
        )


def save_session(session: SessionResult, db_path: Path = DB_PATH) -> None:
    """Persist a completed session and all its question results."""
    with get_db(db_path) as conn:
        # Upsert session row
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions
              (session_id, timestamp, total_q, correct_count, wrong_count, score_pct, sections_json)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                session.session_id,
                session.timestamp,
                session.total_questions,
                session.correct_count,
                session.wrong_count,
                session.score_pct,
                json.dumps(session.sections),
            ),
        )

        # Session-section mapping
        conn.executemany(
            "INSERT OR IGNORE INTO session_sections (session_id, section_id) VALUES (?,?)",
            [(session.session_id, sid) for sid in session.sections],
        )

        # Question results
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            """
            INSERT INTO question_results
              (session_id, question_id, section_id, user_label, is_correct, timestamp)
            VALUES (?,?,?,?,?,?)
            """,
            [
                (
                    session.session_id,
                    r.question_id,
                    r.section_id,
                    r.user_label,
                    1 if r.is_correct else 0,
                    now,
                )
                for r in session.results
            ],
        )
    logger.info(f"Session {session.session_id} saved. Score: {session.score_pct:.1f}%")


# Read Operations

def get_sessions_for_sections(
    section_ids: list[int], db_path: Path = DB_PATH
) -> list[dict]:
    """Return all sessions that included ANY of the given sections."""
    placeholders = ",".join("?" * len(section_ids))
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT s.*
            FROM sessions s
            JOIN session_sections ss ON ss.session_id = s.session_id
            WHERE ss.section_id IN ({placeholders})
            ORDER BY s.timestamp DESC
            """,
            section_ids,
        ).fetchall()
    return [dict(r) for r in rows]


def has_prior_history(section_ids: list[int], db_path: Path = DB_PATH) -> bool:
    """Return True if any prior session covered any of these sections."""
    return len(get_sessions_for_sections(section_ids, db_path)) > 0


def get_weak_topics(
    section_ids: list[int], top_n: int = 10, db_path: Path = DB_PATH
) -> list[dict]:
    """
    Return topic_tags with highest wrong-answer rates across prior sessions
    for the given sections. Used for adaptive question generation.
    """
    placeholders = ",".join("?" * len(section_ids))
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                q.topic_tag,
                q.section_id,
                COUNT(*) as attempts,
                SUM(CASE WHEN qr.is_correct = 0 THEN 1 ELSE 0 END) as wrong_count,
                ROUND(
                    SUM(CASE WHEN qr.is_correct = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1
                ) as error_rate
            FROM question_results qr
            JOIN questions q ON q.question_id = qr.question_id
            WHERE q.section_id IN ({placeholders})
              AND q.topic_tag != ''
            GROUP BY q.topic_tag, q.section_id
            HAVING wrong_count > 0
            ORDER BY error_rate DESC, wrong_count DESC
            LIMIT ?
            """,
            section_ids + [top_n],
        ).fetchall()
    return [dict(r) for r in rows]


def get_mastered_question_ids(
    section_ids: list[int], min_correct_streak: int = 2, db_path: Path = DB_PATH
) -> list[str]:
    """
    Return question IDs that the user has answered correctly in the last
    min_correct_streak attempts (considered 'mastered'; avoid over-repetition).
    """
    placeholders = ",".join("?" * len(section_ids))
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT qr.question_id,
                   MIN(qr.is_correct) as all_correct_recent
            FROM (
                SELECT question_id, is_correct,
                       ROW_NUMBER() OVER (
                           PARTITION BY question_id ORDER BY timestamp DESC
                       ) as rn
                FROM question_results
                WHERE section_id IN ({placeholders})
            ) qr
            WHERE qr.rn <= ?
            GROUP BY qr.question_id
            HAVING all_correct_recent = 1
            """,
            section_ids + [min_correct_streak],
        ).fetchall()
    return [r["question_id"] for r in rows]


def get_previously_asked_question_ids(
    section_ids: list[int], db_path: Path = DB_PATH
) -> list[str]:
    """Return all question IDs previously asked for these sections."""
    placeholders = ",".join("?" * len(section_ids))
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT question_id
            FROM question_results
            WHERE section_id IN ({placeholders})
            """,
            section_ids,
        ).fetchall()
    return [r["question_id"] for r in rows]


def get_kb_snapshot(top_n: int = 5, db_path: Path = DB_PATH) -> KBSnapshot:
    """
    Return a human-readable snapshot of the top-N most recent sessions.
    Used for evaluation output.
    """
    with get_db(db_path) as conn:
        sessions = conn.execute(
            """
            SELECT * FROM sessions ORDER BY timestamp DESC LIMIT ?
            """,
            (top_n,),
        ).fetchall()

    records = []
    for s in sessions:
        sec_ids = json.loads(s["sections_json"])
        weak = get_weak_topics(sec_ids, top_n=5, db_path=db_path)
        records.append(
            KBSnapshotRecord(
                session_id=s["session_id"],
                timestamp=s["timestamp"],
                sections=sec_ids,
                score_pct=s["score_pct"],
                total_questions=s["total_q"],
                correct_count=s["correct_count"],
                wrong_count=s["wrong_count"],
                weak_topics=[w["topic_tag"] for w in weak],
            )
        )

    return KBSnapshot(
        snapshot_taken_at=datetime.now(timezone.utc).isoformat(),
        sessions_shown=len(records),
        records=records,
    )


def get_section_stats(section_ids: list[int], db_path: Path = DB_PATH) -> dict:
    """Return aggregate stats for given sections."""
    placeholders = ",".join("?" * len(section_ids))
    with get_db(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(DISTINCT qr.session_id) as sessions,
                COUNT(*) as total_attempts,
                SUM(qr.is_correct) as total_correct
            FROM question_results qr
            WHERE qr.section_id IN ({placeholders})
            """,
            section_ids,
        ).fetchone()
    if row and row["total_attempts"]:
        return {
            "sessions": row["sessions"],
            "total_attempts": row["total_attempts"],
            "avg_score_pct": round(row["total_correct"] * 100 / row["total_attempts"], 1),
        }
    return {"sessions": 0, "total_attempts": 0, "avg_score_pct": None}
