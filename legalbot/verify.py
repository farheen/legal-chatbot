"""Check a generated answer against the passages it was given and against the case database.

Every case citation in the answer must exist in the database (or at least appear in a source
passage); every passage marker must point at a passage that was actually supplied; every
quotation must appear verbatim in a passage. Anything else is flagged for the lawyer.
"""
import re
import sqlite3
from dataclasses import asdict, dataclass, field

from .citations import find_citations, normalize_cite
from .search import Passage

MARKER_RE = re.compile(r"\[(P\d+(?:\s*,\s*P?\d+)*)\]")
QUOTE_RE = re.compile(r"[\"“]([^\"”]{25,})[\"”]")


@dataclass
class CitationCheck:
    cite: str
    status: str  # 'verified' (in database), 'in_sources' (only mentioned in a passage), 'unverified'
    case_id: int | None = None
    case_name: str | None = None


@dataclass
class Verification:
    citations: list[CitationCheck] = field(default_factory=list)
    used_passages: list[int] = field(default_factory=list)  # 1-based passage numbers the answer cites
    invalid_markers: list[str] = field(default_factory=list)
    unmatched_quotes: list[str] = field(default_factory=list)
    uncited_paragraphs: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.invalid_markers or self.unmatched_quotes
            or any(c.status == "unverified" for c in self.citations)
        )

    def to_dict(self) -> dict:
        return {**asdict(self), "ok": self.ok}


def _squash(text: str) -> str:
    return re.sub(r"[\s\"“”'‘’]+", " ", text).strip().lower()


def verify_answer(conn: sqlite3.Connection, answer: str, passages: list[Passage]) -> Verification:
    result = Verification()

    used = set()
    for group in MARKER_RE.findall(answer):
        for token in re.split(r"\s*,\s*", group):
            n = int(token.lstrip("P"))
            if 1 <= n <= len(passages):
                used.add(n)
            else:
                result.invalid_markers.append(f"P{n}")
    result.used_passages = sorted(used)

    passage_cites = {normalize_cite(c) for p in passages for c in find_citations(p.text)}
    passage_cites |= {normalize_cite(p.citation) for p in passages if p.citation}
    for cite in find_citations(answer):
        norm = normalize_cite(cite)
        row = conn.execute(
            """SELECT c.id, c.name_abbreviation FROM case_citations cc JOIN cases c ON c.id = cc.case_id
               WHERE cc.norm_cite = ? LIMIT 1""",
            (norm,),
        ).fetchone()
        if row:
            result.citations.append(CitationCheck(cite, "verified", row["id"], row["name_abbreviation"]))
        elif norm in passage_cites:
            result.citations.append(CitationCheck(cite, "in_sources"))
        else:
            result.citations.append(CitationCheck(cite, "unverified"))

    haystack = " ".join(_squash(p.text) for p in passages)
    for quote in QUOTE_RE.findall(answer):
        q = _squash(quote).strip(" .,;:")
        if q and q not in haystack:
            result.unmatched_quotes.append(quote)

    for para in re.split(r"\n\s*\n", answer):
        stripped = para.strip()
        if len(stripped) > 200 and not MARKER_RE.search(stripped):
            result.uncited_paragraphs += 1
    return result
