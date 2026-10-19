"""Web app: login, hybrid search, streamed cited answers, and full-opinion view.

    uvicorn app.server:app --port 8000

Required environment: ANTHROPIC_API_KEY (or another Anthropic credential source) and
LEGALBOT_SECRET_KEY (signs session cookies). Set LEGALBOT_DEV=1 to allow plain-HTTP cookies locally.
"""
import json
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from legalbot import answer as answer_mod
from legalbot.auth import audit, authenticate
from legalbot.db import connect
from legalbot.search import Filters, Searcher
from legalbot.treatment import treatment
from legalbot.verify import verify_answer

STATIC_DIR = Path(__file__).parent / "static"
DEV = os.environ.get("LEGALBOT_DEV") == "1"
# Store question text in the audit log? Questions can contain client confidences.
AUDIT_QUESTIONS = os.environ.get("LEGALBOT_AUDIT_QUESTIONS", "1") == "1"
MAX_HISTORY_TURNS = 6

components: dict = {}


def load_components() -> dict:
    """Embedder, vector index and reranker are loaded once and shared; each request gets its own db connection."""
    from legalbot.search import default_searcher

    use_vectors = os.environ.get("LEGALBOT_USE_VECTORS", "1") == "1"
    use_reranker = os.environ.get("LEGALBOT_USE_RERANKER", "0") == "1"
    s = default_searcher(connect(), use_vectors=use_vectors, use_reranker=use_reranker)
    return {"embedder": s.embedder, "vector_index": s.vector_index, "reranker": s.reranker}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not components:
        components.update(load_components())
    yield


app = FastAPI(title="Legal research assistant", lifespan=lifespan, docs_url=None, redoc_url=None)

secret = os.environ.get("LEGALBOT_SECRET_KEY")
if not secret:
    if not DEV:
        raise RuntimeError("Set LEGALBOT_SECRET_KEY (or LEGALBOT_DEV=1 for local development).")
    secret = secrets.token_hex(32)
app.add_middleware(
    SessionMiddleware, secret_key=secret, session_cookie="legalbot_session",
    max_age=8 * 3600, same_site="strict", https_only=not DEV,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


# --- auth ---------------------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=500)


_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()
LOCKOUT_ATTEMPTS, LOCKOUT_WINDOW = 5, 15 * 60


@app.post("/api/login")
def login(body: LoginRequest, request: Request, conn=Depends(db)):
    now = time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(body.username, []) if now - t < LOCKOUT_WINDOW]
        _failures[body.username] = recent
        if len(recent) >= LOCKOUT_ATTEMPTS:
            raise HTTPException(429, "Too many failed attempts. Try again later.")
    if not authenticate(conn, body.username, body.password):
        with _failures_lock:
            _failures[body.username].append(now)
        audit(conn, body.username, "login_failed")
        raise HTTPException(401, "Invalid username or password")
    request.session.clear()
    request.session["user"] = body.username
    audit(conn, body.username, "login")
    return {"user": body.username}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(user: str = Depends(current_user)):
    return {"user": user}


# --- research -----------------------------------------------------------------------------------
@app.get("/api/filters")
def filter_options(user: str = Depends(current_user), conn=Depends(db)):
    jurisdictions = conn.execute(
        "SELECT jurisdiction, COUNT(*) AS n FROM cases WHERE jurisdiction IS NOT NULL GROUP BY jurisdiction ORDER BY n DESC"
    ).fetchall()
    dates = conn.execute("SELECT MIN(decision_date), MAX(decision_date) FROM cases").fetchone()
    return {
        "jurisdictions": [{"name": r["jurisdiction"], "count": r["n"]} for r in jurisdictions],
        "date_min": dates[0], "date_max": dates[1],
    }


class FilterModel(BaseModel):
    jurisdictions: list[str] = Field(default_factory=list, max_length=60)
    court: str | None = Field(default=None, max_length=200)
    date_from: str | None = Field(default=None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=20000)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    filters: FilterModel = Field(default_factory=FilterModel)
    history: list[Turn] = Field(default_factory=list)
    k: int = Field(default=8, ge=1, le=15)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/ask")
def ask(body: AskRequest, user: str = Depends(current_user)):
    def events():
        conn = connect()
        try:
            searcher = Searcher(conn, **components)
            filters = Filters(**body.filters.model_dump())
            passages = searcher.search(body.question, filters, k=body.k)
            yield _sse("sources", [p.to_dict() for p in passages])

            history = [t.model_dump() for t in body.history][-2 * MAX_HISTORY_TURNS :]
            # The API requires the conversation to start with a user turn.
            while history and history[0]["role"] != "user":
                history.pop(0)
            text = []
            try:
                for delta in answer_mod.stream_answer(body.question, passages, history):
                    text.append(delta)
                    yield _sse("delta", delta)
            except answer_mod.AnswerError as e:
                yield _sse("error", str(e))
                return

            verification = verify_answer(conn, "".join(text), passages)
            yield _sse("verification", verification.to_dict())
            audit(conn, user, "ask", {
                "question": body.question if AUDIT_QUESTIONS else None,
                "filters": body.filters.model_dump(),
                "case_ids": sorted({p.case_id for p in passages}),
                "verification_ok": verification.ok,
            })
            yield _sse("done", {})
        finally:
            conn.close()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/api/cases/{case_id}")
def get_case(case_id: int, user: str = Depends(current_user), conn=Depends(db)):
    case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        raise HTTPException(404, "Case not found")
    opinions = conn.execute(
        "SELECT idx, type, author, text FROM opinions WHERE case_id = ? ORDER BY idx", (case_id,)
    ).fetchall()
    cites = [r["cite"] for r in conn.execute("SELECT cite FROM case_citations WHERE case_id = ?", (case_id,))]
    audit(conn, user, "view_case", {"case_id": case_id})
    return {
        "case": {k: case[k] for k in case.keys()},
        "citations": cites,
        "opinions": [dict(o) for o in opinions],
        "treatment": treatment(conn, case_id, scan_limit=100),
    }


# --- static UI ----------------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/static/{name}")
def static_file(name: str):
    path = (STATIC_DIR / name).resolve()
    if path.parent != STATIC_DIR.resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)
