"""SQLite storage: cases, opinions, passage chunks (with an FTS5 keyword index), and citation links."""
import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,              -- 'cap' or 'courtlistener'
    source_id TEXT NOT NULL,
    name TEXT,
    name_abbreviation TEXT,
    citation TEXT,                     -- primary citation as printed, e.g. '1 A.3d 281'
    decision_date TEXT,                -- ISO date (may be YYYY or YYYY-MM for old cases)
    court TEXT,
    court_abbr TEXT,
    jurisdiction TEXT,
    docket_number TEXT,
    first_page TEXT,
    last_page TEXT,
    url TEXT,
    head_matter TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS cases_jurisdiction ON cases (jurisdiction);
CREATE INDEX IF NOT EXISTS cases_date ON cases (decision_date);

CREATE TABLE IF NOT EXISTS case_citations (   -- every citation a case is published under
    case_id INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    cite TEXT NOT NULL,
    norm_cite TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS case_citations_norm ON case_citations (norm_cite);
CREATE INDEX IF NOT EXISTS case_citations_case ON case_citations (case_id);

CREATE TABLE IF NOT EXISTS opinions (
    case_id INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    type TEXT,                         -- majority, concurrence, dissent, ...
    author TEXT,
    text TEXT NOT NULL,
    PRIMARY KEY (case_id, idx)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    opinion_idx INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_case ON chunks (case_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5 (
    text, content='chunks', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS cites_to (         -- outgoing citations from a case's opinions
    case_id INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    cite TEXT NOT NULL,
    norm_cite TEXT NOT NULL,
    cited_source_id TEXT                  -- CAP id of the cited case when CAP resolved it
);
CREATE INDEX IF NOT EXISTS cites_to_case ON cites_to (case_id);
CREATE INDEX IF NOT EXISTS cites_to_norm ON cites_to (norm_cite);

CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    username TEXT,
    action TEXT NOT NULL,
    detail TEXT
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn
