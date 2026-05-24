"""
LLM Integration
───────────────
Primary: Google Gemini Flash (via REST API — free tier)
Mock: deterministic MCQs generated from section text (for offline/test use)

Set GEMINI_API_KEY in your .env file.
For offline/demo mode set USE_MOCK_LLM=true — no API key needed.
"""

import json
import logging
import os
import re
import time
import uuid
import urllib.request
import urllib.error
from typing import Optional

from app.config import GEMINI_API_KEY, GEMINI_MODEL, SECTION_TITLES
from app.models import MCQ, MCQChoice

logger = logging.getLogger(__name__)

USE_MOCK = os.getenv("USE_MOCK_LLM", "false").lower() == "true"


# Prompt Builders

def _build_cold_start_prompt(section_id: int, section_text: str, n_questions: int) -> str:
    title = SECTION_TITLES.get(section_id, f"Section {section_id}")
    return f"""You are an expert quiz designer. Generate exactly {n_questions} multiple choice questions from the document section below.

SECTION: {section_id}. {title}

DOCUMENT TEXT:
\"\"\"{section_text[:7000]}\"\"\"

RULES:
1. Exactly {n_questions} MCQs.
2. Each MCQ: exactly 4 choices labelled A, B, C, D.
3. One correct answer only.
4. Choices must be plausible and non-trivial.
5. Explanation cites a specific fact from the text.
6. topic_tag: 2-5 words describing the sub-topic tested.
7. Test factual recall and comprehension, not opinion.

Return ONLY a valid JSON array, no markdown, no extra text:
[
  {{
    "question": "...",
    "choices": [
      {{"label": "A", "text": "..."}},
      {{"label": "B", "text": "..."}},
      {{"label": "C", "text": "..."}},
      {{"label": "D", "text": "..."}}
    ],
    "correct_label": "A",
    "explanation": "...",
    "topic_tag": "..."
  }}
]"""


def _build_adaptive_prompt(section_id: int, section_text: str, n_questions: int,
                            weak_topics: list, prior_questions: list) -> str:
    title = SECTION_TITLES.get(section_id, f"Section {section_id}")

    weak_str = ""
    if weak_topics:
        lines = "\n".join(
            f"  - '{w['topic_tag']}' (error rate: {w['error_rate']}%)"
            for w in weak_topics
        )
        weak_str = f"\nWEAK AREAS — PRIORITIZE these topics:\n{lines}\n"

    prior_str = ""
    if prior_questions:
        lines = "\n".join(f"  - {q}" for q in prior_questions[:8])
        prior_str = f"\nPREVIOUSLY ASKED (do NOT repeat these):\n{lines}\n"

    return f"""You are an expert adaptive quiz designer. Generate {n_questions} MCQs from the section below.

SECTION: {section_id}. {title}
{weak_str}{prior_str}
DOCUMENT TEXT:
\"\"\"{section_text[:7000]}\"\"\"

ADAPTIVE RULES:
1. If weak areas listed, at least {min(n_questions, max(1, len(weak_topics)))} questions MUST target those topics.
2. Do NOT repeat previously asked questions.
3. Exactly {n_questions} MCQs, 4 choices each (A B C D), one correct answer.
4. Explanation cites a specific fact. topic_tag is 2-5 words.

Return ONLY a valid JSON array, no markdown:
[{{"question":"...","choices":[{{"label":"A","text":"..."}},{{"label":"B","text":"..."}},{{"label":"C","text":"..."}},{{"label":"D","text":"..."}}],"correct_label":"A","explanation":"...","topic_tag":"..."}}]"""


# Gemini HTTP Caller

def _call_gemini(prompt: str) -> str:
    """Call Gemini Flash via REST API using urllib (no extra packages needed)."""
    if not GEMINI_API_KEY:
        raise EnvironmentError(
            "GEMINI_API_KEY not set. "
            "Get a free key at https://aistudio.google.com/app/apikey "
            "and add it to your .env file as: GEMINI_API_KEY=your_key_here"
        )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_gemini_with_retry(prompt: str, max_attempts: int = 3) -> str:
    """Call Gemini with exponential backoff on rate-limit / server errors."""
    for attempt in range(max_attempts):
        try:
            return _call_gemini(prompt)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < max_attempts - 1:
                wait = 2 ** attempt
                logger.warning(
                    f"Gemini rate limit / server error (attempt {attempt + 1}). "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                raise
        except urllib.error.URLError as e:
            raise EnvironmentError(
                f"Cannot reach Gemini API: {e}. "
                "Check your internet connection."
            )


# Mock Generator

def _generate_mock_mcqs(section_id: int, n_questions: int,
                        weak_topics: list = None) -> list:
    """
    Generate deterministic mock MCQs from real section content.
    Used when USE_MOCK_LLM=true — no API key needed.
    Questions are grounded in actual dossier text, not random placeholders.
    """
    from app.pdf_parser import get_section_text
    text = get_section_text(section_id)

    # Pull real lines from the section for grounding
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 40][:30]

    title = SECTION_TITLES.get(section_id, f"Section {section_id}")
    topic_pool = weak_topics or [{"topic_tag": f"section-{section_id}-core"}]

    mock_templates = [
        {
            "question": f"According to Section {section_id} of the SLATEFALL dossier, which of the following is TRUE about {title}?",
            "choices": [
                {"label": "A", "text": lines[0][:80] if lines else "Inertial Suspension is the primary power"},
                {"label": "B", "text": "SLATEFALL operates without any operational restrictions"},
                {"label": "C", "text": "All PAMC operatives share identical capabilities"},
                {"label": "D", "text": "The dossier covers events from 2010 to 2020 only"},
            ],
            "correct_label": "A",
            "explanation": f"Section {section_id} ({title}) explicitly states: {lines[0][:120] if lines else 'See section text'}",
            "topic_tag": topic_pool[0]["topic_tag"] if topic_pool else f"section-{section_id}",
        },
        {
            "question": f"What is a key characteristic documented in Section {section_id} ({title})?",
            "choices": [
                {"label": "A", "text": "No restrictions apply to any PAMC operative"},
                {"label": "B", "text": lines[1][:80] if len(lines) > 1 else "The asset has multiple documented abilities"},
                {"label": "C", "text": "The Cooperative operates with unlimited budget"},
                {"label": "D", "text": "All engagements result in successful outcomes"},
            ],
            "correct_label": "B",
            "explanation": f"Section {section_id} documents: {lines[1][:120] if len(lines) > 1 else 'key characteristics of this topic'}",
            "topic_tag": topic_pool[min(1, len(topic_pool) - 1)]["topic_tag"] if topic_pool else f"section-{section_id}",
        },
        {
            "question": f"In Section {section_id}, which statement correctly describes {title}?",
            "choices": [
                {"label": "A", "text": "All information is publicly available without restriction"},
                {"label": "B", "text": "The asset has no documented vulnerabilities"},
                {"label": "C", "text": lines[2][:80] if len(lines) > 2 else "Specific protocols are documented for operations"},
                {"label": "D", "text": "No prior operational history exists"},
            ],
            "correct_label": "C",
            "explanation": f"As documented in Section {section_id}: {lines[2][:120] if len(lines) > 2 else 'see section for details'}",
            "topic_tag": f"section-{section_id}-detail",
        },
        {
            "question": f"Which of the following is documented as a factual detail in Section {section_id}?",
            "choices": [
                {"label": "A", "text": "The PAMC was founded in 1990"},
                {"label": "B", "text": "SLATEFALL has never been injured in operations"},
                {"label": "C", "text": "All threat tiers require solo engagement"},
                {"label": "D", "text": lines[3][:80] if len(lines) > 3 else "Specific procedural requirements apply"},
            ],
            "correct_label": "D",
            "explanation": f"Section {section_id} records: {lines[3][:120] if len(lines) > 3 else 'specific factual details as described'}",
            "topic_tag": f"section-{section_id}-facts",
        },
        {
            "question": f"What does Section {section_id} ({title}) specify regarding operational requirements?",
            "choices": [
                {"label": "A", "text": lines[4][:80] if len(lines) > 4 else "Documented requirements are followed strictly"},
                {"label": "B", "text": "No operational requirements exist for any PAMC operative"},
                {"label": "C", "text": "All operations are unauthorized by design"},
                {"label": "D", "text": "Equipment is irrelevant to operational success"},
            ],
            "correct_label": "A",
            "explanation": f"Per Section {section_id}: {lines[4][:120] if len(lines) > 4 else 'operational requirements are documented'}",
            "topic_tag": f"section-{section_id}-requirements",
        },
    ]

    mcqs = []
    for i in range(min(n_questions, len(mock_templates))):
        t = mock_templates[i]
        mcqs.append(MCQ(
            question_id=str(uuid.uuid4()),
            section_id=section_id,
            question=t["question"],
            choices=[MCQChoice(**c) for c in t["choices"]],
            correct_label=t["correct_label"],
            explanation=t["explanation"],
            topic_tag=t["topic_tag"],
        ))

    # Pad with variants if more questions requested than templates
    while len(mcqs) < n_questions:
        base = mock_templates[len(mcqs) % len(mock_templates)]
        mcqs.append(MCQ(
            question_id=str(uuid.uuid4()),
            section_id=section_id,
            question=base["question"] + f" (variant {len(mcqs) + 1})",
            choices=[MCQChoice(**c) for c in base["choices"]],
            correct_label=base["correct_label"],
            explanation=base["explanation"],
            topic_tag=base["topic_tag"],
        ))

    return mcqs


#JSON Parser

def _clean_json(raw: str) -> str:
    """Strip markdown fences from LLM output."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _parse_mcq_response(raw: str, section_id: int) -> list:
    """Parse the Gemini JSON response into a list of MCQ objects."""
    cleaned = _clean_json(raw)

    # Extract the JSON array even if there is leading text
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw snippet: {raw[:400]}")
        raise ValueError(f"Gemini returned invalid JSON: {e}")

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array from Gemini, got {type(data)}")

    mcqs = []
    for item in data:
        required = {"question", "choices", "correct_label", "explanation", "topic_tag"}
        if not required.issubset(item.keys()):
            logger.warning(f"MCQ missing fields, skipping: {required - set(item.keys())}")
            continue
        choices = [MCQChoice(**c) for c in item["choices"]]
        if len(choices) != 4:
            logger.warning(f"MCQ has {len(choices)} choices (expected 4), skipping")
            continue
        mcqs.append(MCQ(
            question_id=str(uuid.uuid4()),
            section_id=section_id,
            question=item["question"],
            choices=choices,
            correct_label=item["correct_label"].upper(),
            explanation=item["explanation"],
            topic_tag=item.get("topic_tag", ""),
        ))

    return mcqs


# Public Entry Point

def generate_mcqs(
    section_id: int,
    section_text: str,
    n_questions: int,
    weak_topics: Optional[list] = None,
    mastered_question_ids: Optional[list] = None,
    prior_question_texts: Optional[list] = None,
    is_adaptive: bool = False,
) -> list:
    """
    Generate MCQs for a section using Gemini Flash.

    Args:
        section_id:            Section number (1-10)
        section_text:          Raw text of the section from the PDF
        n_questions:           How many MCQs to generate
        weak_topics:           Topics with high error rates (adaptive mode)
        mastered_question_ids: Question IDs to de-prioritize (adaptive mode)
        prior_question_texts:  Previously asked questions to avoid repeating
        is_adaptive:           True = use adaptive prompt, False = cold-start prompt

    Returns:
        List of MCQ objects ready to serve to the user
    """
    if USE_MOCK:
        logger.info(f"Mock mode — skipping Gemini call for section {section_id}")
        return _generate_mock_mcqs(section_id, n_questions, weak_topics)

    if is_adaptive and (weak_topics or prior_question_texts):
        prompt = _build_adaptive_prompt(
            section_id=section_id,
            section_text=section_text,
            n_questions=n_questions,
            weak_topics=weak_topics or [],
            prior_questions=prior_question_texts or [],
        )
        logger.info(
            f"Adaptive MCQ generation | section={section_id} | "
            f"weak topics={[w['topic_tag'] for w in (weak_topics or [])[:3]]}"
        )
    else:
        prompt = _build_cold_start_prompt(section_id, section_text, n_questions)
        logger.info(f"Cold-start MCQ generation | section={section_id}")

    raw = _call_gemini_with_retry(prompt)
    mcqs = _parse_mcq_response(raw, section_id)

    if len(mcqs) < n_questions:
        logger.warning(
            f"Section {section_id}: requested {n_questions} MCQs, Gemini returned {len(mcqs)}"
        )

    return mcqs