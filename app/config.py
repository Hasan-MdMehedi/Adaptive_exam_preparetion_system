"""Central configuration loaded from environment variables / .env file."""
import os
from pathlib import Path

# Load .env manually (python-dotenv available)
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

BASE_DIR = Path(__file__).parent.parent

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
PDF_PATH: Path = BASE_DIR / os.getenv("PDF_PATH", "data/SLATEFALL_DOSSIER.pdf")
DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/knowledge_base.db")
CHROMA_PATH: Path = BASE_DIR / os.getenv("CHROMA_PATH", "data/chroma_db")
MCQ_PER_SECTION: int = int(os.getenv("MCQ_PER_SECTION", "5"))
USE_MOCK_LLM: bool = os.getenv("USE_MOCK_LLM", "false").lower() == "true"

GEMINI_MODEL: str = "gemini-3.5-flash"

VALID_SECTIONS: list = list(range(1, 11))

SECTION_TITLES: dict = {
    1: "Identity, Background, and Public Status",
    2: "Powers, Abilities, and Documented Limits",
    3: "Origin and Key Historical Events",
    4: "Equipment, Gear, and Specialized Technology",
    5: "Operational Tactics and Combat Doctrine",
    6: "Allies, Networks, and Known Affiliations",
    7: "Adversaries and Documented Threats",
    8: "Known Bases, Safehouses, and Operational Territory",
    9: "Case Files: Documented Engagements and Incidents",
    10: "Glossary, Codenames, and Reference Tables",
}
