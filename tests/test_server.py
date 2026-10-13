import json
import os

import pytest
from fastapi.testclient import TestClient

from legalbot.auth import add_user
from legalbot.db import connect
from legalbot.ingest import upsert_case
from tests.conftest import CASES


@pytest.fixture
def client(monkeypatch):
    from app import server

    db = connect()
    with db:
        db.execute("DELETE FROM cases")
        for case in CASES:
            upsert_case(db, case)
    add_user(db, "alice", "correct horse battery")
    server.components.update({"embedder": None, "vector_index": None, "reranker": None})
    server._failures.clear()

    def fake_stream(question, passages, history=None, client=None):
        yield "Inspection requires a credible basis [P1]. "
        yield "See 1 A.3d 281."

    monkeypatch.setattr(server.answer_mod, "stream_answer", fake_stream)
    with TestClient(server.app) as c:
        yield c


def login(c, password="correct horse battery"):
    return c.post("/api/login", json={"username": "alice", "password": password})


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_requires_login(client):
    assert client.get("/api/filters").status_code == 401
    assert client.post("/api/ask", json={"question": "anything"}).status_code == 401


def test_bad_password_then_lockout(client):
    for _ in range(5):
        assert login(client, "wrong password!!").status_code == 401
    assert login(client).status_code == 429


def test_ask_streams_sources_answer_and_verification(client):
    assert login(client).status_code == 200
    res = client.post("/api/ask", json={"question": "credible basis books and records", "filters": {"jurisdictions": ["Delaware"]}})
    assert res.status_code == 200
    events = parse_sse(res.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "sources" and kinds[-1] == "done" and "verification" in kinds
    sources = events[0][1]
    assert sources and all(s["jurisdiction"] == "Delaware" for s in sources)
    verification = dict(events)["verification"]
    assert verification["ok"] and verification["citations"][0]["status"] == "verified"

    db = connect()
    actions = [r[0] for r in db.execute("SELECT action FROM audit_log WHERE username = 'alice' ORDER BY id")]
    assert actions[-1] == "ask"


def test_case_view_and_filters(client):
    login(client)
    f = client.get("/api/filters").json()
    assert {j["name"] for j in f["jurisdictions"]} == {"Delaware", "Pennsylvania"}
    case_id = connect().execute("SELECT id FROM cases WHERE source_id = '1002'").fetchone()[0]
    body = client.get(f"/api/cases/{case_id}").json()
    assert body["treatment"]["citing_count"] == 2
    assert client.get("/api/cases/999999").status_code == 404


def test_security_headers_and_static(client):
    res = client.get("/")
    assert res.status_code == 200 and "frame-ancestors 'none'" in res.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/..%2Fserver.py").status_code == 404


def test_input_validation(client):
    login(client)
    assert client.post("/api/ask", json={"question": "x"}).status_code == 422
    assert client.post("/api/ask", json={"question": "valid question", "filters": {"date_from": "yesterday"}}).status_code == 422
