"""
Data models — using Python stdlib dataclasses (no pydantic required).
Provides .model_dump() for JSON serialization compatibility.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


def _model_dump(obj):
    """Recursively convert dataclass to dict."""
    if hasattr(obj, '__dataclass_fields__'):
        return {k: _model_dump(v) for k, v in asdict(obj).items()}
    elif isinstance(obj, list):
        return [_model_dump(i) for i in obj]
    return obj


class ModelMixin:
    def model_dump(self):
        return _model_dump(self)


@dataclass
class MCQChoice(ModelMixin):
    label: str
    text: str


@dataclass
class MCQ(ModelMixin):
    question_id: str
    section_id: int
    question: str
    choices: list
    correct_label: str
    explanation: str
    topic_tag: str = ""
    source_chunk: str = ""


@dataclass
class UserAnswer(ModelMixin):
    question_id: str
    chosen_label: str


@dataclass
class QuestionResult(ModelMixin):
    question_id: str
    section_id: int
    question: str
    choices: list
    correct_label: str
    user_label: str
    is_correct: bool
    explanation: str
    topic_tag: str


@dataclass
class SessionResult(ModelMixin):
    session_id: str
    sections: list
    timestamp: str
    total_questions: int
    correct_count: int
    wrong_count: int
    score_pct: float
    results: list


@dataclass
class StartPrepResponse(ModelMixin):
    session_id: str
    sections: list
    questions: list
    is_returning: bool


@dataclass
class SubmitAnswersResponse(ModelMixin):
    session_result: SessionResult


@dataclass
class KBSnapshotRecord(ModelMixin):
    session_id: str
    timestamp: str
    sections: list
    score_pct: float
    total_questions: int
    correct_count: int
    wrong_count: int
    weak_topics: list


@dataclass
class KBSnapshot(ModelMixin):
    snapshot_taken_at: str
    sessions_shown: int
    records: list


@dataclass
class SectionInfo(ModelMixin):
    section_id: int
    title: str
    has_history: bool
    past_sessions: int
    average_score_pct: Optional[float] = None
