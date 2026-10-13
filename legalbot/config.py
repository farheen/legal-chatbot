"""Paths and settings. Everything is resolved from the repo root so scripts work from any cwd.

Override any setting with the environment variable of the same name.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


DATA_DIR = _path("LEGALBOT_DATA_DIR", ROOT / "data")
RAW_DIR = _path("LEGALBOT_RAW_DIR", DATA_DIR / "raw")
DB_PATH = _path("LEGALBOT_DB_PATH", DATA_DIR / "legal.db")
INDEX_DIR = _path("LEGALBOT_INDEX_DIR", DATA_DIR / "index")

CAP_BASE_URL = "https://static.case.law/"
COURTLISTENER_BASE_URL = "https://www.courtlistener.com/api/rest/v4/"

# Retrieval
EMBED_MODEL = os.environ.get("LEGALBOT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RERANK_MODEL = os.environ.get("LEGALBOT_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
CHUNK_TARGET_CHARS = 1200
CHUNK_MAX_CHARS = 2000

# Generation
LLM_MODEL = os.environ.get("LEGALBOT_LLM_MODEL", "claude-opus-5-5")
LLM_EFFORT = os.environ.get("LEGALBOT_LLM_EFFORT", "high")
