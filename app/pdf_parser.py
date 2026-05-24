"""
PDF Parsing Module
─────────────────
Extracts text from SLATEFALL_DOSSIER.pdf and splits it into the 10 named sections.
Uses pdfplumber for reliable text extraction from machine-readable PDFs.
"""

import re
import logging
from pathlib import Path
from functools import lru_cache

import pdfplumber

from app.config import PDF_PATH, SECTION_TITLES

logger = logging.getLogger(__name__)

# Section heading patterns as they appear in the PDF
SECTION_PATTERNS = {
    1: r"Section\s+1[\.\s]",
    2: r"Section\s+2[\.\s]",
    3: r"Section\s+3[\.\s]",
    4: r"Section\s+4[\.\s]",
    5: r"Section\s+5[\.\s]",
    6: r"Section\s+6[\.\s]",
    7: r"Section\s+7[\.\s]",
    8: r"Section\s+8[\.\s]",
    9: r"Section\s+9[\.\s]",
    10: r"Section\s+10[\.\s]",
}


def extract_full_text(pdf_path: Path = PDF_PATH) -> str:
    """Extract all text from the PDF as a single string using pdfplumber."""
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n".join(pages)


@lru_cache(maxsize=1)
def extract_sections(pdf_path: str = str(PDF_PATH)) -> dict[int, str]:
    """
    Parse the PDF and return a dict mapping section_id -> section text.
    Results are cached since the PDF doesn't change between runs.
    """
    logger.info(f"Parsing PDF: {pdf_path}")
    full_text = extract_full_text(Path(pdf_path))

    # Find the character positions where each section begins
    section_positions: dict[int, int] = {}
    for sec_id, pattern in SECTION_PATTERNS.items():
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            section_positions[sec_id] = match.start()
            logger.debug(f"Section {sec_id} found at position {match.start()}")
        else:
            logger.warning(f"Section {sec_id} not found in PDF text")

    if not section_positions:
        raise ValueError("Could not find any section markers in PDF. Check PDF format.")

    # Sort by position to determine boundaries
    sorted_secs = sorted(section_positions.items(), key=lambda x: x[1])

    sections: dict[int, str] = {}
    for i, (sec_id, start_pos) in enumerate(sorted_secs):
        # Text runs from this section's start to the next section's start (or EOF)
        if i + 1 < len(sorted_secs):
            end_pos = sorted_secs[i + 1][1]
        else:
            end_pos = len(full_text)

        section_text = full_text[start_pos:end_pos].strip()
        sections[sec_id] = section_text
        logger.info(f"Section {sec_id} extracted: {len(section_text)} chars")

    return sections


def get_section_text(section_id: int) -> str:
    """Return the text for a specific section."""
    sections = extract_sections()
    if section_id not in sections:
        raise ValueError(f"Section {section_id} not found. Valid: {list(sections.keys())}")
    return sections[section_id]


def chunk_section(section_text: str, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
    """
    Split section text into overlapping chunks suitable for embedding.
    Splits on paragraph boundaries where possible.
    """
    paragraphs = [p.strip() for p in section_text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = (current_chunk + "\n\n" + para).strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # Start new chunk with overlap from previous
            if len(current_chunk) > overlap and current_chunk:
                current_chunk = current_chunk[-overlap:] + "\n\n" + para
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [section_text[:chunk_size]]


def get_section_summary(section_id: int, max_chars: int = 3000) -> str:
    """Return the first max_chars of a section (used as context for LLM)."""
    text = get_section_text(section_id)
    return text[:max_chars] if len(text) > max_chars else text


if __name__ == "__main__":
    # Quick smoke test
    logging.basicConfig(level=logging.DEBUG)
    secs = extract_sections()
    for sid, txt in secs.items():
        print(f"Section {sid}: {len(txt)} chars | Preview: {txt[:80]!r}")
