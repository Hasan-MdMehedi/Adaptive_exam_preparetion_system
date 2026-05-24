"""
Vector Store Module — Lightweight JSON-based Chunk Store:
Tried to use a simple JSON file store with keyword-based retrieval. This is functionally sufficient
for the MCQ generation use-case (section text is passed directly to LLM).

Architecture note: The interface mirrors the chromadb-based design so swapping
back requires only changing this file.
"""

import json
import logging
import re
from pathlib import Path
from functools import lru_cache

from app.config import CHROMA_PATH
from app.pdf_parser import extract_sections, chunk_section

logger = logging.getLogger(__name__)

INDEX_FILE = Path(str(CHROMA_PATH)).parent / "chunk_index.json"


def _tf_score(query: str, text: str) -> float:
    if not query:
        return 0.0
    q_terms = set(re.findall(r"\w+", query.lower()))
    t_terms = re.findall(r"\w+", text.lower())
    if not t_terms:
        return 0.0
    return sum(1 for t in t_terms if t in q_terms) / len(t_terms)


def index_pdf(chroma_path: str = str(CHROMA_PATH), force: bool = False) -> int:
    """Extract and store all section chunks. Returns chunk count."""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not force and INDEX_FILE.exists():
        with open(INDEX_FILE) as f:
            data = json.load(f)
        count = len(data.get("chunks", []))
        logger.info(f"Chunk index already has {count} chunks.")
        return count

    sections = extract_sections()
    chunks_data = []
    for sec_id, text in sections.items():
        for i, chunk in enumerate(chunk_section(text)):
            chunks_data.append({"id": f"sec{sec_id}_chunk{i}", "section_id": sec_id,
                                 "chunk_index": i, "text": chunk})

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump({"chunks": chunks_data}, f, ensure_ascii=False)

    logger.info(f"Indexed {len(chunks_data)} chunks across {len(sections)} sections")
    return len(chunks_data)


@lru_cache(maxsize=1)
def _load_index() -> list:
    if not INDEX_FILE.exists():
        return []
    with open(INDEX_FILE) as f:
        return json.load(f).get("chunks", [])


def retrieve_chunks(section_id: int, query: str = "", n_results: int = 5,
                    chroma_path: str = str(CHROMA_PATH)) -> list:
    all_chunks = _load_index()
    section_chunks = [c for c in all_chunks if c["section_id"] == section_id]
    if not section_chunks:
        return []
    if query:
        scored = sorted(section_chunks, key=lambda c: _tf_score(query, c["text"]), reverse=True)
    else:
        scored = sorted(section_chunks, key=lambda c: c["chunk_index"])
    return [c["text"] for c in scored[:n_results]]


def get_indexed_sections(chroma_path: str = str(CHROMA_PATH)) -> list:
    return sorted({c["section_id"] for c in _load_index()})
