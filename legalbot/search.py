"""Hybrid passage search: keyword (SQLite FTS5 / BM25) + dense vectors, fused, then re-ranked.

Lawyers search by exact citations, case names and terms of art, which dense retrieval alone
handles poorly; keyword search alone misses paraphrases. Each retriever contributes its top
results, Reciprocal Rank Fusion merges them, and an optional cross-encoder re-scores the
merged list against the question.
"""
import re
import sqlite3
from dataclasses import asdict, dataclass, field

from .citations import find_citations, normalize_cite

RRF_K = 60
MAX_PASSAGES_PER_CASE = 3
FILTERED_KEYWORD_POOL = 5000  # keyword hits ranked before filters are applied
AUTHORITY_POOL = 20  # top fused passages scanned for frequently cited authorities
AUTHORITY_BONUS = 0.5  # reranker-score bonus per retrieved case citing an authority

# "Revlon v. MacAndrews", "Smith v. Van Gorkom": party name tokens around "v."
CASE_NAME_RE = re.compile(r"([A-Z][\w&'’.-]*(?:\s+[A-Z&][\w&'’.-]*)*)\s+v\.?\s+([A-Z][\w&'’.-]*(?:\s+[A-Z][\w&'’.-]*)*)")

_STOPWORDS = set(
    "a an and are as at be by can could did do does for from had has have how i if in into is it its may "
    "must not of on or our shall should that the their there these this those to under was were what when "
    "where whether which who why will with would you".split()
)


@dataclass
class Filters:
    jurisdictions: list[str] = field(default_factory=list)
    court: str | None = None  # substring match on court name
    date_from: str | None = None  # ISO date, inclusive
    date_to: str | None = None

    def sql(self) -> tuple[str, list]:
        clauses, params = [], []
        if self.jurisdictions:
            clauses.append(f"c.jurisdiction IN ({','.join('?' * len(self.jurisdictions))})")
            params += self.jurisdictions
        if self.court:
            clauses.append("c.court LIKE ?")
            params.append(f"%{self.court}%")
        if self.date_from:
            clauses.append("c.decision_date >= ?")
            params.append(self.date_from)
        if self.date_to:
            clauses.append("c.decision_date <= ?")
            params.append(self.date_to + "￿")  # include partial dates like 2010-08 within the bound
        return (" AND ".join(clauses) or "1"), params

    def active(self) -> bool:
        return bool(self.jurisdictions or self.court or self.date_from or self.date_to)


@dataclass
class Passage:
    chunk_id: int
    case_id: int
    case_name: str
    citation: str | None
    court: str | None
    jurisdiction: str | None
    decision_date: str | None
    opinion_type: str | None
    opinion_author: str | None
    text: str
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def fts_query(question: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted phrases kept, other terms OR-ed (BM25 ranks them)."""
    phrases = re.findall(r'"([^"]+)"', question)
    rest = re.sub(r'"[^"]*"', " ", question)
    terms = [t for t in re.findall(r"[A-Za-z0-9§]+", rest.lower()) if t not in _STOPWORDS and len(t) > 1]
    parts = [f'"{p.replace(chr(34), "")}"' for p in phrases] + [f'"{t}"' for t in dict.fromkeys(terms)]
    return " OR ".join(parts) if parts else None


class Searcher:
    def __init__(self, conn: sqlite3.Connection, embedder=None, vector_index=None, reranker=None):
        self.conn = conn
        self.embedder = embedder
        self.vector_index = vector_index
        self.reranker = reranker

    # --- individual retrievers -------------------------------------------------------------
    def keyword(self, question: str, filters: Filters, k: int) -> list[int]:
        query = fts_query(question)
        if not query:
            return []
        # Rank inside FTS alone, then filter: joining cases into the MATCH query makes SQLite
        # score every match through the join, which is ~10x slower on a large collection.
        limit = FILTERED_KEYWORD_POOL if filters.active() else k
        ranked = [r[0] for r in self.conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (query, limit))]
        if not filters.active():
            return ranked
        return self._apply_filters(ranked, filters)[:k]

    def _apply_filters(self, chunk_ids: list[int], filters: Filters) -> list[int]:
        """Keep chunks whose case passes the filters, preserving order."""
        where, params = filters.sql()
        allowed = set()
        for start in range(0, len(chunk_ids), 900):
            batch = chunk_ids[start : start + 900]
            allowed.update(r[0] for r in self.conn.execute(
                # CROSS JOIN pins the join order: look up these chunk ids first, not every case in the filter.
                f"""SELECT ch.id FROM chunks ch CROSS JOIN cases c ON c.id = ch.case_id
                    WHERE ch.id IN ({','.join('?' * len(batch))}) AND {where}""",
                [*batch, *params],
            ))
        return [i for i in chunk_ids if i in allowed]

    def dense(self, question: str, filters: Filters, k: int) -> list[int]:
        if not (self.embedder and self.vector_index):
            return []
        allowed = None
        if filters.active():
            where, params = filters.sql()
            allowed = [r[0] for r in self.conn.execute(
                f"SELECT ch.id FROM chunks ch JOIN cases c ON c.id = ch.case_id WHERE {where}", params)]
        hits = self.vector_index.search(self.embedder.embed_query(question), k, allowed)
        return [chunk_id for chunk_id, _ in hits]

    def by_citation(self, question: str, filters: Filters) -> list[int]:
        """Cases the question cites directly (e.g. 'What did 1 A.3d 281 hold?')."""
        cites = [normalize_cite(c) for c in find_citations(question)]
        if not cites:
            return []
        where, params = filters.sql()
        rows = self.conn.execute(
            f"""SELECT DISTINCT c.id FROM case_citations cc JOIN cases c ON c.id = cc.case_id
                WHERE cc.norm_cite IN ({','.join('?' * len(cites))}) AND {where}""",
            [*cites, *params],
        ).fetchall()
        return [r[0] for r in rows]

    def by_case_name(self, question: str, filters: Filters, max_cases: int = 2) -> list[int]:
        """Cases named in the question ('Revlon v. MacAndrews'), most-cited first when the name is ambiguous."""
        case_ids = []
        for first, second in CASE_NAME_RE.findall(question):
            where, params = filters.sql()
            rows = self.conn.execute(
                f"""SELECT c.id FROM cases c WHERE c.name_abbreviation LIKE ? AND c.name_abbreviation LIKE ? AND {where}
                    LIMIT 50""",
                [f"%{first.split()[-1]}% v. %", f"% v. {second.split()[0]}%", *params],
            ).fetchall()
            ranked = sorted((r[0] for r in rows), key=self.citing_count, reverse=True)
            case_ids += ranked[:max_cases]
        return case_ids

    def citing_count(self, case_id: int) -> int:
        cites = [r[0] for r in self.conn.execute("SELECT norm_cite FROM case_citations WHERE case_id = ?", (case_id,))]
        if not cites:
            return 0
        return self.conn.execute(
            f"SELECT COUNT(DISTINCT case_id) FROM cites_to WHERE norm_cite IN ({','.join('?' * len(cites))})", cites
        ).fetchone()[0]

    def cited_authorities(self, passages: list[Passage], filters: Filters, max_cases: int = 4) -> dict[int, int]:
        """Cases cited by several different retrieved cases: usually the leading authority on the point.

        Returns {case_id: number of retrieved cases citing it} for cases in the database that pass the filters.
        """
        citing: dict[str, set[int]] = {}
        for p in passages:
            for cite in find_citations(p.text):
                citing.setdefault(normalize_cite(cite), set()).add(p.case_id)
        frequent = sorted((c for c, cases in citing.items() if len(cases) >= 2), key=lambda c: -len(citing[c]))
        where, params = filters.sql()
        found: dict[int, int] = {}
        for cite in frequent:
            row = self.conn.execute(
                f"SELECT c.id FROM case_citations cc JOIN cases c ON c.id = cc.case_id WHERE cc.norm_cite = ? AND {where}",
                [cite, *params],
            ).fetchone()
            if row and row[0] not in found:
                found[row[0]] = len(citing[cite])
                if len(found) >= max_cases:
                    break
        return found

    def best_chunks(self, case_id: int, question: str, n: int = 2) -> list[int]:
        """The chunks of one case that share the most query terms (ties go to earlier chunks)."""
        terms = {t for t in re.findall(r"[a-z0-9]+", question.lower()) if t not in _STOPWORDS and len(t) > 2}
        rows = self.conn.execute(
            "SELECT id, text FROM chunks WHERE case_id = ? ORDER BY opinion_idx, ordinal", (case_id,)
        ).fetchall()
        scored = sorted(rows, key=lambda r: -len(terms & set(re.findall(r"[a-z0-9]+", r["text"].lower()))))
        return [r["id"] for r in scored[:n]]

    # --- combined ---------------------------------------------------------------------------
    def search(self, question: str, filters: Filters | None = None, k: int = 8, candidates: int = 50) -> list[Passage]:
        filters = filters or Filters()
        scores: dict[int, float] = {}
        for ranking in (self.keyword(question, filters, candidates), self.dense(question, filters, candidates)):
            for rank, chunk_id in enumerate(ranking):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
        fused = sorted(scores, key=scores.get, reverse=True)[:candidates]

        # Leading authorities cited across the top results join the pool, scored by how many cite them.
        authorities = self.cited_authorities(self.load(fused[:AUTHORITY_POOL]), filters)
        for case_id, n_citing in authorities.items():
            for chunk_id in self.best_chunks(case_id, question, n=1):
                scores[chunk_id] = max(scores.get(chunk_id, 0.0), n_citing / (2 * (RRF_K + 1)))
                if chunk_id not in fused:
                    fused.append(chunk_id)

        passages = self.load(fused)
        for p in passages:
            p.score = scores[p.chunk_id]
        if self.reranker and passages:
            rerank_scores = self.reranker.predict([(question, p.text) for p in passages])
            for p, s in zip(passages, rerank_scores):
                p.score = float(s) + (AUTHORITY_BONUS * authorities[p.case_id] if p.case_id in authorities else 0.0)
        passages.sort(key=lambda p: p.score, reverse=True)

        # Cases the question names or cites come first.
        pinned_cases = list(dict.fromkeys(self.by_citation(question, filters) + self.by_case_name(question, filters)))
        pinned = self.load([c for case_id in pinned_cases for c in self.best_chunks(case_id, question)])

        selected, seen, per_case = [], set(), {}
        for p in pinned + passages:
            if p.chunk_id in seen or per_case.get(p.case_id, 0) >= MAX_PASSAGES_PER_CASE:
                continue
            seen.add(p.chunk_id)
            per_case[p.case_id] = per_case.get(p.case_id, 0) + 1
            selected.append(p)
            if len(selected) >= k:
                break
        return selected

    def load(self, chunk_ids: list[int]) -> list[Passage]:
        if not chunk_ids:
            return []
        rows = self.conn.execute(
            f"""SELECT ch.id, ch.case_id, ch.text, c.name_abbreviation, c.name, c.citation, c.court,
                       c.jurisdiction, c.decision_date, o.type, o.author
                FROM chunks ch JOIN cases c ON c.id = ch.case_id
                LEFT JOIN opinions o ON o.case_id = ch.case_id AND o.idx = ch.opinion_idx
                WHERE ch.id IN ({','.join('?' * len(chunk_ids))})""",
            chunk_ids,
        ).fetchall()
        by_id = {
            r["id"]: Passage(
                chunk_id=r["id"], case_id=r["case_id"], case_name=r["name_abbreviation"] or r["name"],
                citation=r["citation"], court=r["court"], jurisdiction=r["jurisdiction"],
                decision_date=r["decision_date"], opinion_type=r["type"], opinion_author=r["author"], text=r["text"],
            )
            for r in rows
        }
        return [by_id[i] for i in chunk_ids if i in by_id]  # ids missing from the db (stale index) are dropped


def default_searcher(conn: sqlite3.Connection, use_vectors: bool = True, use_reranker: bool = True) -> Searcher:
    """Searcher with whatever components are available on this machine."""
    from .config import INDEX_DIR, RERANK_MODEL

    embedder = vector_index = reranker = None
    if use_vectors and (INDEX_DIR / "chunks.faiss").exists():
        from .vectors import Embedder, VectorIndex

        embedder = Embedder()
        vector_index = VectorIndex(embedder.dim)
    if use_reranker:
        from sentence_transformers import CrossEncoder

        reranker = CrossEncoder(RERANK_MODEL)
    return Searcher(conn, embedder, vector_index, reranker)
