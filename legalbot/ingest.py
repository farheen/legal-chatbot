"""Load Caselaw Access Project volume zips into the database.

Cases are read straight out of each zip (no extraction to disk): every volume zip stores its
cases under the same names (json/0001-01.json, ...), so extracting several zips into one
directory silently overwrites earlier cases.

    python -m legalbot.ingest                      # every zip under data/raw/
    python -m legalbot.ingest --jurisdiction Delaware --jurisdiction Pennsylvania
"""
import argparse
import json
import sqlite3
import zipfile
from pathlib import Path

from tqdm import tqdm

from .chunking import chunk_text
from .citations import normalize_cite
from .config import RAW_DIR
from .db import connect


def upsert_case(conn: sqlite3.Connection, case: dict, source: str = "cap") -> int:
    """Insert or replace one case (CAP JSON shape) with its opinions, chunks and citations. Returns the row id."""
    source_id = str(case["id"])
    conn.execute("DELETE FROM cases WHERE source = ? AND source_id = ?", (source, source_id))

    citations = case.get("citations") or []
    official = next((c["cite"] for c in citations if c.get("type") == "official"), None)
    body = case.get("casebody") or {}
    court = case.get("court") or {}
    cur = conn.execute(
        """INSERT INTO cases (source, source_id, name, name_abbreviation, citation, decision_date, court,
                              court_abbr, jurisdiction, docket_number, first_page, last_page, url, head_matter)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source, source_id, case.get("name"), case.get("name_abbreviation"),
            official or (citations[0]["cite"] if citations else None),
            case.get("decision_date"), court.get("name"), court.get("name_abbreviation"),
            (case.get("jurisdiction") or {}).get("name_long"), case.get("docket_number"),
            case.get("first_page"), case.get("last_page"), case.get("url"), body.get("head_matter"),
        ),
    )
    case_id = cur.lastrowid

    conn.executemany(
        "INSERT INTO case_citations (case_id, cite, norm_cite) VALUES (?, ?, ?)",
        [(case_id, c["cite"], normalize_cite(c["cite"])) for c in citations if c.get("cite")],
    )

    for idx, opinion in enumerate(body.get("opinions") or []):
        text = opinion.get("text") or ""
        if not text.strip():
            continue
        conn.execute(
            "INSERT INTO opinions (case_id, idx, type, author, text) VALUES (?, ?, ?, ?, ?)",
            (case_id, idx, opinion.get("type"), opinion.get("author"), text),
        )
        conn.executemany(
            "INSERT INTO chunks (case_id, opinion_idx, ordinal, text) VALUES (?, ?, ?, ?)",
            [(case_id, idx, n, chunk) for n, chunk in enumerate(chunk_text(text))],
        )

    rows = []
    for ref in case.get("cites_to") or []:
        cited_ids = ref.get("case_ids") or [None]
        rows.extend(
            (case_id, ref["cite"], normalize_cite(ref["cite"]), str(cid) if cid is not None else None)
            for cid in cited_ids
        )
    conn.executemany("INSERT INTO cites_to (case_id, cite, norm_cite, cited_source_id) VALUES (?, ?, ?, ?)", rows)
    return case_id


def iter_zip_cases(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.startswith("json/") and name.endswith(".json"):
                yield json.loads(zf.read(name))


def ingest(raw_dir: Path = RAW_DIR, jurisdictions: set[str] | None = None, conn: sqlite3.Connection | None = None) -> int:
    conn = conn or connect()
    zips = sorted(raw_dir.rglob("*.zip"))
    count = 0
    for zip_path in tqdm(zips, desc="Ingesting volumes"):
        with conn:  # one transaction per volume
            for case in iter_zip_cases(zip_path):
                if jurisdictions and (case.get("jurisdiction") or {}).get("name_long") not in jurisdictions:
                    continue
                upsert_case(conn, case)
                count += 1
    with conn:
        conn.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('optimize')")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--jurisdiction", action="append", help="Only ingest cases from this jurisdiction (repeatable)")
    args = parser.parse_args()
    n = ingest(args.raw_dir, set(args.jurisdiction) if args.jurisdiction else None)
    print(f"Ingested {n} cases.")


if __name__ == "__main__":
    main()
