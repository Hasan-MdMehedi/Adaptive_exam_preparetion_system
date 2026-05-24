"""
Prep Engine — Core Orchestration
──────────────────────────────────
Coordinates: PDF parsing → KB lookup → LLM MCQ generation → scoring → KB persistence.
This is the single entry-point for both the FastAPI layer and the CLI.
"""

import uuid
import random
import logging
from datetime import datetime, timezone

from app.config import MCQ_PER_SECTION, SECTION_TITLES
from app.models import (
    MCQ, QuestionResult, SessionResult, UserAnswer,
    StartPrepResponse, SubmitAnswersResponse,
)
from app.pdf_parser import get_section_text
from app.database import (
    init_db, save_questions, save_session,
    has_prior_history, get_weak_topics,
    get_mastered_question_ids, get_previously_asked_question_ids,
    get_sessions_for_sections,
)
from app.llm import generate_mcqs

logger = logging.getLogger(__name__)

# In-memory store for active (not-yet-submitted) sessions
# Maps session_id -> list[MCQ]
_active_sessions: dict[str, list[MCQ]] = {}


def start_prep_session(
    section_ids: list[int],
    mcq_per_section: int | None = None,
) -> StartPrepResponse:
    """
    STEP 1 + STEP 2 of the PREP FLOW:
    - Check KB for prior history
    - Generate MCQs (adaptive if returning, cold-start if new)
    - Store questions in DB and in memory
    """
    init_db()
    n = mcq_per_section or MCQ_PER_SECTION
    session_id = str(uuid.uuid4())

    is_returning = has_prior_history(section_ids)
    logger.info(
        f"Session {session_id} | sections={section_ids} | "
        f"returning={is_returning} | mcq_per_section={n}"
    )

    # Gather adaptive context once (across all requested sections)
    weak_topics = get_weak_topics(section_ids) if is_returning else []
    mastered_ids = get_mastered_question_ids(section_ids) if is_returning else []
    prior_ids = get_previously_asked_question_ids(section_ids) if is_returning else []

    # Retrieve prior question texts for de-duplication prompt
    prior_question_texts: list[str] = []
    if is_returning:
        # We'll collect these lazily while generating per section
        pass

    all_mcqs: list[MCQ] = []

    for sec_id in section_ids:
        try:
            section_text = get_section_text(sec_id)
        except ValueError as e:
            logger.error(f"Cannot load section {sec_id}: {e}")
            continue

        # Section-scoped weak topics
        sec_weak = [w for w in weak_topics if w["section_id"] == sec_id]

        mcqs = generate_mcqs(
            section_id=sec_id,
            section_text=section_text,
            n_questions=n,
            weak_topics=sec_weak if is_returning else None,
            mastered_question_ids=mastered_ids if is_returning else None,
            prior_question_texts=prior_question_texts if is_returning else None,
            is_adaptive=is_returning,
        )

        all_mcqs.extend(mcqs)

    if not all_mcqs:
        raise RuntimeError("No MCQs could be generated. Check LLM configuration.")

    # Persist question definitions
    save_questions(all_mcqs)

    # Store in memory for answer submission
    _active_sessions[session_id] = all_mcqs

    return StartPrepResponse(
        session_id=session_id,
        sections=section_ids,
        questions=all_mcqs,
        is_returning=is_returning,
    )


def submit_answers(
    session_id: str,
    answers: list[UserAnswer],
) -> SubmitAnswersResponse:
    """
    STEP 3 + STEP 4 + STEP 5 of the PREP FLOW:
    - Score each answer
    - Build SessionResult with per-question detail
    - Persist to KB
    """
    if session_id not in _active_sessions:
        raise KeyError(f"Session '{session_id}' not found. Start a new prep session first.")

    questions = _active_sessions[session_id]
    q_map = {q.question_id: q for q in questions}

    results: list[QuestionResult] = []
    correct_count = 0

    for answer in answers:
        q = q_map.get(answer.question_id)
        if not q:
            logger.warning(f"Unknown question_id {answer.question_id}, skipping")
            continue

        is_correct = answer.chosen_label.upper() == q.correct_label.upper()
        if is_correct:
            correct_count += 1

        results.append(
            QuestionResult(
                question_id=q.question_id,
                section_id=q.section_id,
                question=q.question,
                choices=q.choices,
                correct_label=q.correct_label,
                user_label=answer.chosen_label.upper(),
                is_correct=is_correct,
                explanation=q.explanation,
                topic_tag=q.topic_tag,
            )
        )

    total = len(results)
    wrong_count = total - correct_count
    score_pct = round(correct_count * 100 / total, 2) if total else 0.0

    session_result = SessionResult(
        session_id=session_id,
        sections=list({r.section_id for r in results}),
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_questions=total,
        correct_count=correct_count,
        wrong_count=wrong_count,
        score_pct=score_pct,
        results=results,
    )

    save_session(session_result)

    # Clean up in-memory session
    del _active_sessions[session_id]

    logger.info(
        f"Session {session_id} scored: {correct_count}/{total} ({score_pct}%)"
    )

    return SubmitAnswersResponse(session_result=session_result)


def simulate_answers(questions: list[MCQ], wrong_pct: float = 0.35) -> list[UserAnswer]:
    """
    Simulate realistic user answers for evaluation scenario B.
    wrong_pct fraction of answers will be deliberately wrong.
    """
    labels = ["A", "B", "C", "D"]
    answers = []
    for q in questions:
        if random.random() < wrong_pct:
            # Pick a random wrong answer
            wrong_labels = [l for l in labels if l != q.correct_label]
            chosen = random.choice(wrong_labels)
        else:
            chosen = q.correct_label
        answers.append(UserAnswer(question_id=q.question_id, chosen_label=chosen))
    return answers


def run_full_session(
    section_ids: list[int],
    mcq_per_section: int | None = None,
    simulate: bool = False,
    wrong_pct: float = 0.35,
) -> tuple[StartPrepResponse, SubmitAnswersResponse]:
    prep = start_prep_session(section_ids, mcq_per_section)

    if simulate:
        answers = simulate_answers(prep.questions, wrong_pct=wrong_pct)
    else:
        raise ValueError("Interactive answer collection not supported in run_full_session. "
                         "Use simulate=True or call start_prep_session / submit_answers separately.")

    result = submit_answers(prep.session_id, answers)
    return prep, result
