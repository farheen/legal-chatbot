from legalbot.courtlistener import CourtListener, import_court, opinion_text, to_case
from legalbot.db import connect

RESULT = {
    "cluster_id": 555, "caseName": "Leung Trust v. Amazon.com, Inc.", "caseNameFull": "",
    "dateFiled": "2025-07-28", "docketNumber": "487, 2024", "citation": ["330 A.3d 100"],
    "court": "Supreme Court of Delaware", "court_citation_string": "Del.",
    "absolute_url": "/opinion/555/leung/", "opinions": [{"id": 9001}],
}
OPINION = {
    "id": 9001, "type": "020lead", "author_str": "Griffiths",
    "plain_text": "", "html_with_citations": "<p>Under Section 220, see 1 A.3d 281, a stockholder must show a proper purpose.</p><p>Affirmed.</p>",
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.headers, self.urls = {}, []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        if url.endswith("/search/"):
            return FakeResponse({"results": [RESULT], "next": None})
        return FakeResponse(OPINION)


def test_opinion_text_strips_html():
    assert opinion_text(OPINION) == "Under Section 220, see 1 A.3d 281, a stockholder must show a proper purpose.\nAffirmed.\n"


def test_to_case_maps_fields():
    case = to_case(RESULT, [OPINION])
    assert case["citations"] == [{"type": "official", "cite": "330 A.3d 100"}]
    assert case["casebody"]["opinions"][0]["type"] == "majority"
    assert case["cites_to"] == [{"cite": "1 A.3d 281"}]


def test_import_court_writes_searchable_case(monkeypatch, tmp_path):
    db = tmp_path / "cl.db"
    monkeypatch.setattr("legalbot.courtlistener.connect", lambda: connect(db))
    session = FakeSession()
    n = import_court(CourtListener(token="t", session=session, pause=0), "del", filed_after="2025-01-01")
    assert n == 1 and session.headers["Authorization"] == "Token t"
    conn = connect(db)
    row = conn.execute("SELECT source, jurisdiction, citation FROM cases").fetchone()
    assert tuple(row) == ("courtlistener", "Delaware", "330 A.3d 100")
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'stockholder'").fetchone()[0] == 1
