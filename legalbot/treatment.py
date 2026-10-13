"""Subsequent-treatment signals from the cases in our own database.

This is NOT a citator (Shepard's / KeyCite). It only sees later cases that are in this
database, and flags possible negative treatment with a keyword heuristic. Use it to decide
what to check, never to conclude that a case is still good law.
"""
import re
import sqlite3

# Strong signals only: "reversed"/"vacated" near a citation usually describe the citing case's own
# disposition or another case's history, and flagged every heavily cited case.
NEGATIVE_RE = re.compile(
    r"overrul\w*|abrogat\w*|disapprov\w*|supersed\w*|no longer (?:good|valid|binding) law|"
    r"declin\w* to follow|limited to its (?:own )?facts|called into (?:question|doubt)",
    re.IGNORECASE,
)
WINDOW = 150


def _case_cites(conn: sqlite3.Connection, case_id: int) -> tuple[list[str], list[str], str | None]:
    cites = conn.execute("SELECT cite, norm_cite FROM case_citations WHERE case_id = ?", (case_id,)).fetchall()
    row = conn.execute("SELECT source, source_id FROM cases WHERE id = ?", (case_id,)).fetchone()
    cap_id = row["source_id"] if row and row["source"] == "cap" else None
    return [c["cite"] for c in cites], [c["norm_cite"] for c in cites], cap_id


def _citing_where(conn: sqlite3.Connection, case_id: int) -> tuple[str, list] | None:
    _, norm_cites, cap_id = _case_cites(conn, case_id)
    if not norm_cites and not cap_id:
        return None
    sql = f"(t.norm_cite IN ({','.join('?' * len(norm_cites)) or "''"}) OR t.cited_source_id = ?) AND t.case_id != ?"
    return sql, [*norm_cites, cap_id, case_id]


def citing_count(conn: sqlite3.Connection, case_id: int) -> int:
    where = _citing_where(conn, case_id)
    if not where:
        return 0
    return conn.execute(f"SELECT COUNT(DISTINCT t.case_id) FROM cites_to t WHERE {where[0]}", where[1]).fetchone()[0]


def citing_cases(conn: sqlite3.Connection, case_id: int, limit: int = 200) -> list[dict]:
    """Cases in the database whose opinions cite this case, newest first."""
    where = _citing_where(conn, case_id)
    if not where:
        return []
    rows = conn.execute(
        f"""SELECT DISTINCT c.id, c.name_abbreviation, c.citation, c.decision_date, c.court
            FROM cites_to t JOIN cases c ON c.id = t.case_id
            WHERE {where[0]}
            ORDER BY c.decision_date DESC LIMIT ?""",
        [*where[1], limit],
    ).fetchall()
    return [dict(r) for r in rows]


def treatment(conn: sqlite3.Connection, case_id: int, scan_limit: int = 200) -> dict:
    """Citing-case count plus snippets where a citing opinion uses negative-treatment language near the cite.

    Only the newest `scan_limit` citing cases are scanned for negative language.
    """
    cites, _, _ = _case_cites(conn, case_id)
    citing = citing_cases(conn, case_id, scan_limit)
    cite_res = [re.compile(r"\s*".join(re.escape(part) for part in cite.split())) for cite in cites]
    signals = []
    for case in citing:
        for (text,) in conn.execute("SELECT text FROM opinions WHERE case_id = ?", (case["id"],)):
            for cite_re in cite_res:
                for m in cite_re.finditer(text):
                    window = text[max(0, m.start() - WINDOW) : m.end() + WINDOW]
                    neg = NEGATIVE_RE.search(window)
                    if neg:
                        signals.append({**case, "term": neg.group(0), "snippet": " ".join(window.split())})
                        break
    return {
        "citing_count": citing_count(conn, case_id),
        "scanned": len(citing),
        "citing_cases": citing[:10],
        "negative_signals": signals[:10],
        "note": "Based only on cases in this database; confirm with a citator (Shepard's, KeyCite, or equivalent).",
    }
