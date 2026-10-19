import numpy as np

from legalbot.db import connect
from legalbot.ingest import ingest, upsert_case
from legalbot.search import Filters, Searcher, fts_query
from legalbot.treatment import treatment
from tests.conftest import CASES


def test_ingest_keeps_cases_with_colliding_file_names(zip_dir, tmp_path):
    conn = connect(tmp_path / "ingest.db")
    assert ingest(zip_dir, conn=conn) == 2
    names = {r[0] for r in conn.execute("SELECT name_abbreviation FROM cases")}
    assert names == {CASES[0]["name_abbreviation"], CASES[2]["name_abbreviation"]}


def test_ingest_jurisdiction_filter(zip_dir, tmp_path):
    conn = connect(tmp_path / "ingest.db")
    assert ingest(zip_dir, jurisdictions={"Pennsylvania"}, conn=conn) == 1


def test_all_opinions_are_kept(conn):
    rows = conn.execute(
        "SELECT o.type FROM opinions o JOIN cases c ON c.id = o.case_id WHERE c.source_id = '1003' ORDER BY o.idx"
    ).fetchall()
    assert [r[0] for r in rows] == ["majority", "dissent"]


def test_reingest_replaces_case(conn):
    with conn:
        upsert_case(conn, CASES[0])
    assert conn.execute("SELECT COUNT(*) FROM cases WHERE source_id = '1001'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'westland'").fetchone()[0] == 1


def test_fts_query_is_safe():
    assert fts_query('what is a "proper purpose" under section 220?') == '"proper purpose" OR "section" OR "220"'
    assert fts_query("the of and") is None
    assert fts_query('AND OR NOT ") (') is None or '"' in fts_query('AND OR NOT ") (')


def test_keyword_search_finds_relevant_case(conn):
    results = Searcher(conn).search("credible basis to inspect books and records under section 220")
    assert results and results[0].case_name.startswith(("City of Westland", "Security First"))


def test_filters_restrict_results(conn):
    s = Searcher(conn)
    assert s.search("vehicle suppression", Filters(jurisdictions=["Delaware"])) == []
    pa = s.search("vehicle suppression", Filters(jurisdictions=["Pennsylvania"]))
    assert pa and all(p.jurisdiction == "Pennsylvania" for p in pa)
    assert s.search("books and records", Filters(date_to="2000-01-01"))[0].citation == "923 A.2d 810"


def test_citation_in_question_pins_that_case(conn):
    results = Searcher(conn).search("What did 1 A.3d 281 hold?")
    assert results[0].citation == "1 A.3d 281"


class FakeEmbedder:
    dim = 2

    def embed_query(self, text):
        return np.array([1.0, 0.0], dtype="float32")


class FakeIndex:
    def __init__(self, chunk_id):
        self.chunk_id = chunk_id
        self.allowed_seen = None

    def search(self, query, k, allowed_ids=None):
        self.allowed_seen = allowed_ids
        return [(self.chunk_id, 0.9)] if allowed_ids is None or self.chunk_id in allowed_ids else []


def test_dense_results_are_fused_and_filtered(conn):
    smith_chunk = conn.execute(
        "SELECT ch.id FROM chunks ch JOIN cases c ON c.id = ch.case_id WHERE c.source_id = '1003' LIMIT 1"
    ).fetchone()[0]
    index = FakeIndex(smith_chunk)
    s = Searcher(conn, FakeEmbedder(), index)
    # No keyword overlap with the Smith case, so it can only come from the dense retriever.
    assert any(p.chunk_id == smith_chunk for p in s.search("automobile exception"))
    assert s.search("zzz", Filters(jurisdictions=["Delaware"])) == []
    assert smith_chunk not in index.allowed_seen


def test_treatment_finds_citing_cases_and_negative_signal(conn):
    case_id = conn.execute("SELECT id FROM cases WHERE source_id = '1002'").fetchone()[0]
    t = treatment(conn, case_id)
    assert t["citing_count"] == 2
    assert [s["name_abbreviation"] for s in t["negative_signals"]] == ["Later v. Case"]
