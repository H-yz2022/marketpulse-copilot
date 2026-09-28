"""FastAPI backend for MarketPulse Copilot.

Run locally:   uvicorn marketpulse.api.main:app --reload
Interactive API docs are served at /docs (Swagger UI).

The built React frontend (frontend/dist) is served from the same origin, so a
single container deploys the whole app.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from marketpulse import __version__, analytics, db
from marketpulse.api import ratelimit
from marketpulse.config import BASE_DIR, settings
from marketpulse.llm.client import LLMUnavailableError
from marketpulse.llm.sql_guard import UnsafeSQLError

log = logging.getLogger("marketpulse.api")
TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


# --------------------------------------------------------------------------- lifecycle
def _auto_seed() -> None:
    from marketpulse.pipeline import refresh_ticker

    for t in settings.default_tickers:
        try:
            log.info("Auto-seeding %s", t)
            refresh_ticker(t)
        except Exception:  # noqa: BLE001 - one bad ticker shouldn't stop the rest
            log.exception("Auto-seed failed for %s", t)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if settings.auto_seed and not db.list_tickers():
        threading.Thread(target=_auto_seed, name="auto-seed", daemon=True).start()
    yield


app = FastAPI(
    title="MarketPulse Copilot API",
    version=__version__,
    description="Agentic LLM research workspace over market data and SEC filings.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
# Dependency-injection seams: tests swap in a fake LLM client / retriever here.
app.state.llm_client = None
app.state.retrieve_fn = None


# --------------------------------------------------------------------------- errors
@app.exception_handler(LLMUnavailableError)
async def _llm_unavailable(_: Request, exc: LLMUnavailableError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ratelimit.RateLimitExceeded)
async def _rate_limited(_: Request, exc: ratelimit.RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": exc.message})


@app.exception_handler(UnsafeSQLError)
async def _unsafe_sql(_: Request, exc: UnsafeSQLError):
    return JSONResponse(status_code=422, content={"detail": f"Query blocked: {exc}"})


@app.exception_handler(db.DataNotFoundError)
async def _not_found(_: Request, exc: db.DataNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


# --------------------------------------------------------------------------- helpers
def _ticker(value: str) -> str:
    t = value.strip().upper()
    if not TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail=f"Invalid ticker symbol: {value!r}")
    return t


def _client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ai_enabled() -> bool:
    return app.state.llm_client is not None or bool(settings.anthropic_api_key)


def _llm_guard(request: Request, feature: str) -> None:
    """Fail fast if AI is off, then enforce the daily caps before any billed call."""
    if not _ai_enabled():
        raise LLMUnavailableError(
            "AI features are disabled because ANTHROPIC_API_KEY is not set on the server."
        )
    ratelimit.check_and_record(_client_id(request), feature)


def _retrieve_fn():
    if app.state.retrieve_fn is not None:
        return app.state.retrieve_fn
    from marketpulse.rag.hybrid import hybrid_retrieve

    return hybrid_retrieve


# --------------------------------------------------------------------------- schemas
class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    ticker: Optional[str] = None
    rewrite: bool = True


class SqlIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class ChatTurn(BaseModel):
    role: str
    content: str = Field(max_length=6000)


class AgentIn(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)
    mode: Literal["auto", "direct", "plan"] = "auto"


class BriefIn(BaseModel):
    ticker: str


class CompareIn(BaseModel):
    a: str
    b: str


# --------------------------------------------------------------------------- data endpoints
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "ai_enabled": _ai_enabled(),
        "model": settings.anthropic_model,
        "tickers": db.list_tickers(),
    }


@app.get("/api/tickers")
def tickers() -> dict:
    stored = db.list_tickers()
    configured = list(settings.default_tickers)
    return {"stored": stored, "configured": configured, "all": sorted(set(stored) | set(configured))}


@app.get("/api/tickers/{ticker}/overview")
def overview(ticker: str) -> dict:
    return analytics.ticker_overview(_ticker(ticker))


_refresh_locks: dict[str, threading.Lock] = {}
_last_refresh: dict[str, float] = {}
REFRESH_COOLDOWN_S = 60


@app.post("/api/tickers/{ticker}/refresh")
def refresh(ticker: str) -> dict:
    """Re-ingest prices + 10-K filings, re-score sentiment and re-index (10-40s)."""
    from marketpulse.pipeline import refresh_ticker

    t = _ticker(ticker)
    lock = _refresh_locks.setdefault(t, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"{t} is already refreshing")
    try:
        since = time.monotonic() - _last_refresh.get(t, -1e9)
        if since < REFRESH_COOLDOWN_S:
            raise HTTPException(status_code=429, detail=f"{t} was refreshed {int(since)}s ago - try again shortly")
        result = refresh_ticker(t)
        _last_refresh[t] = time.monotonic()
        if result["prices"] == 0:
            raise HTTPException(status_code=404, detail=f"No market data found for {t}. Is the symbol correct?")
        return result
    finally:
        lock.release()


@app.get("/api/watchlist")
def watchlist(tickers: str = Query(..., description="Comma-separated, e.g. AAPL,MSFT,NVDA")) -> dict:
    ts = list(dict.fromkeys(_ticker(t) for t in tickers.split(",") if t.strip()))
    if not ts or len(ts) > 12:
        raise HTTPException(status_code=400, detail="Provide between 1 and 12 tickers")
    return analytics.watchlist(ts)


@app.get("/api/usage")
def usage(request: Request) -> dict:
    return {**ratelimit.usage(_client_id(request)), "ai_enabled": _ai_enabled()}


# --------------------------------------------------------------------------- AI endpoints
@app.post("/api/ask")
def ask(body: AskIn, request: Request) -> dict:
    """Single-shot RAG with the full retrieval pipeline exposed for inspection:
    query rewrite -> dense + BM25 (original AND rewritten queries) -> RRF -> grounded answer."""
    from marketpulse.llm.client import complete_text
    from marketpulse.rag.hybrid import hybrid_retrieve, rewrite_query
    from marketpulse.rag.pipeline import RAG_SYSTEM, format_context

    _llm_guard(request, "ask")
    where = {"ticker": _ticker(body.ticker)} if body.ticker else None
    rewrite = None
    if body.rewrite:
        try:
            rewrite = rewrite_query(body.question, client=app.state.llm_client)
        except ValueError:  # unparseable rewrite -> just use the original query
            rewrite = None
    dense_fn = app.state.retrieve_fn  # None -> real Chroma retriever
    hits = hybrid_retrieve(body.question, n_results=6, where=where, rewrite=rewrite, dense_fn=dense_fn)
    if not hits:
        return {"answer": "No indexed filings match yet - refresh a ticker first.", "sources": [], "rewrite": rewrite}
    prompt = f"Filing excerpts:\n{format_context(hits)}\n\nQuestion: {body.question}"
    answer = complete_text(RAG_SYSTEM, prompt, max_tokens=700, client=app.state.llm_client)
    return {
        "answer": answer,
        "rewrite": rewrite,
        "sources": [
            {
                "n": i,
                **(h.get("metadata") or {}),
                "text": h["text"][:600],
                "matched_by": h.get("matched_by", []),
                "rrf": round(h.get("rrf", 0.0), 4),
            }
            for i, h in enumerate(hits, 1)
        ],
    }


@app.post("/api/sql")
def nl_sql(body: SqlIn, request: Request) -> dict:
    """Natural language -> guarded read-only SQL -> rows + chart spec."""
    from marketpulse.llm.text_to_sql import answer_with_sql

    _llm_guard(request, "sql")
    return answer_with_sql(body.question, client=app.state.llm_client)


@app.post("/api/brief")
def brief(body: BriefIn, request: Request) -> dict:
    from marketpulse.llm.briefs import research_brief

    t = _ticker(body.ticker)
    _llm_guard(request, "brief")
    return research_brief(t, client=app.state.llm_client, retrieve_fn=_retrieve_fn())


@app.post("/api/compare")
def compare(body: CompareIn, request: Request) -> dict:
    from marketpulse.llm.briefs import compare_companies

    a, b = _ticker(body.a), _ticker(body.b)
    if a == b:
        raise HTTPException(status_code=400, detail="Pick two different tickers")
    _llm_guard(request, "compare")
    return compare_companies(a, b, client=app.state.llm_client, retrieve_fn=_retrieve_fn())


def _sse(events: Iterator[dict]) -> Iterator[str]:
    try:
        for event in events:
            yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
    except Exception as exc:  # noqa: BLE001 - report mid-stream failures to the client, don't drop the socket
        log.exception("Agent stream failed")
        payload: Any = {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
        yield f"event: error\ndata: {json.dumps(payload)}\n\n"


@app.post("/api/agent")
def agent(body: AgentIn, request: Request) -> StreamingResponse:
    """Multi-agent analyst (router -> ReAct or planner/executors/synthesizer -> verifier).
    Streams its full trace as Server-Sent Events."""
    from marketpulse.llm.orchestrator import run_orchestrated

    _llm_guard(request, "agent")
    events = run_orchestrated(
        body.question,
        history=[t.model_dump() for t in body.history],
        mode=body.mode,
        client=app.state.llm_client,
        retrieve_fn=app.state.retrieve_fn,
    )
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- frontend
if Path(FRONTEND_DIST).is_dir():
    # Mounted last so every /api route above takes precedence. The frontend
    # uses hash-based routing, so no SPA fallback rewrite is needed.
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
